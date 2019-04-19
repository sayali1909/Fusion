import datetime
import json
from datetime import date, datetime

from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from applications.academic_procedures.models import Thesis
from applications.academic_information.models import Student,Meeting
from applications.globals.models import (Designation, ExtraInfo,
                                         HoldsDesignation, User)
from applications.scholarships.models import Mcm
from applications.gymkhana.models import Club_info

from notification.views import office_dean_PnD_notif

from .forms import *
from .models import *
from .models import (Project_Closure, Project_Extension, Project_Reallocation,
                     Project_Registration)
from .views_office_students import *
from django.core import serializers


def officeOfDeanRSPC(request):
    project=Project_Registration.objects.all()
    project1=Project_Extension.objects.all()
    project2=Project_Closure.objects.all()
    project3=Project_Reallocation.objects.all()

    design = HoldsDesignation.objects.filter(working=request.user)
    print(design)
    desig=[]
    for i in design:
        desig.append(str(i.designation))

    context = {'project':project, 'project1':project1, 'project2':project2, 'project3':project3, 'desig':desig}

    return render(request, "officeModule/officeOfDeanRSPC/officeOfDeanRSPC.html", context)

def _list_find(lst, predicate):
    """
    Find the first element in a list that satisfies the given predicate
    Arguments:
        - lst: List to search through
        - predicate: Predicate that determines what to return
    Returns:
        The first element that satisfies the predicate otherwise None
    """
    for v in lst:
        if predicate(v):
            return v
    return None

def _req_history(req):
    """
    Return requisition history: All tracking rows that are associated with the passet requisition
    """
    return Tracking.objects.filter(file_id=req.assign_file)

@login_required
def officeOfDeanPnD(request):
    """
        Main view for the office of dean (p&d) module.
        Generates four tabs:
            * Dashboard: Shows overview of requisitions and assignments
            * Create Requisition: Form to create new requisitions
            * View Requisitions: Lists all open requisitions and allows Junior Engg.
                to create work assignment from them.
            * View Assignments: Lists all assignments, incoming assignments and
                outgoing assignments. Allows performing actions on incoming assignments.
    """
    user = request.user
    extrainfo = ExtraInfo.objects.get(user=user)

    # Map designations to readable titles.
    deslist={
            'Civil_JE': 'Junior Engg. (Civil)',
            'Civil_AE':'Assistant Engg. (Civil)',
            'Electrical_JE': 'Junior Engg. (Electrical)',
            'Electrical_AE':'Assistant Engg. (Electrical)',
            'EE': 'Executive Engg.',
            'DeanPnD': 'Dean (P&D)',
            'Director': 'Director',
            'None':'Closed'
    }

    holds=HoldsDesignation.objects.filter(working=user)
    designations=[d.designation for d in HoldsDesignation.objects.filter(working=user)]

    # handle createassignment POST request
    if 'createassign' in request.POST:
        print("createassign", request)
        req_id=request.POST.get('req_id')
        requisition=Requisitions.objects.get(pk=req_id)
        description=request.POST.get('description')
        upload_file=request.FILES.get('estimate')
        sender_design=None
        for hold in holds:
            # only allow respective Civil/Electrical JE to create assignment.
            if str(hold.designation.name) == "Civil_JE":
                if requisition.department != "civil":
                    return HttpResponse('Unauthorized', status=401)
                sender_design=hold
                receive=HoldsDesignation.objects.get(designation__name="Civil_AE")
                #fdate = datetime.dat
            elif str(hold.designation.name)=="Electrical_JE":
                if requisition.department != "electrical":
                    return HttpResponse('Unauthorized', status=401)
                sender_design=hold
                receive=HoldsDesignation.objects.get(designation__name="Electrical_AE")
                #fdate = datetime.datetime.now().date()
        if not sender_design:
            return HttpResponse('Unauthorized', status=401)

        # Create file in the File table from filetracking module
        requisition.assign_file = File.objects.create(
                uploader=extrainfo,
                #ref_id=ref_id,
                description=requisition.description,
                subject=requisition.title,
                designation=sender_design.designation,
            )
        requisition.save()

        # Send notifications to all concerned users
        office_dean_PnD_notif(request.user, requisition.userid.user, 'request_accepted')
        office_dean_PnD_notif(request.user, request.user, 'assignment_created')
        office_dean_PnD_notif(request.user, receive.working, 'assignment_received')

        # Create tracking row to send the file to Assistant Engg.
        Tracking.objects.create(
                file_id=requisition.assign_file,
                current_id=extrainfo,
                current_design=sender_design,
                receive_design=receive.designation,
                receiver_id=receive.working,
                remarks=description,
                upload_file=upload_file,
            )
    # Handle delete requisition post request
    # Requisitions are "deleted" by hiding them from requisition lists, but are
    # kept in the database for record-keeping reasons.
    elif 'delete_requisition' in request.POST:
        print('delete requisition')
        hold = HoldsDesignation.objects.get(working=user, designation__name__in=deslist)
        if hold:
            req_id=request.POST.get('req_id')
            try:
                req = Requisitions.objects.get(pk=req_id)
                office_dean_PnD_notif(request.user, req.userid.user, 'request_rejected')
                req.tag = 1 # tag = 1 implies the requisition has been deleted
                req.save()
            except Requisitions.DoesNotExist:
                print('ERROR NOT FOUND 409404040', req_id)
        else:
            return HttpResponse('Unauthorized', status=401)

    # Requisitions that *don't* have as assignment
    req=Requisitions.objects.filter(assign_file__isnull=True, tag=0)
    # all requisitions
    all_req=Requisitions.objects.filter(tag=0)
    # list of all requisitions that have an assignment
    assigned_req=list(Requisitions.objects.filter(assign_file__isnull=False).select_related())
    # use list comprehension to create a list of pairs of (tracking file, corresponding requisition)
    # for incoming tracking files
    incoming_files=[(f, _list_find(assigned_req, lambda r: r.assign_file==f.file_id))
            for f in Tracking.objects.filter(receiver_id=user).filter(is_read=False)]
    # use list comprehension to create a list of pairs of (tracking file, corresponding requisition)
    # for outgoing tracking files
    outgoing_files=[(f, _list_find(assigned_req, lambda r: r.assign_file==f.file_id))
            for f in Tracking.objects.filter(current_id__user=user)]
    # history of assignment, list of pair of (requisition, history list)
    assign_history=[(r, _req_history(r)) for r in assigned_req]


    allfiles=None
    sentfiles=None
    files=''
    req_history = []
    # generate a list of requisitions history to render dashboard
    for r in all_req:
        # in case the requisition has an assignment file
        if r.assign_file:
            # Passed has a list of designations through which req. has passed
            # First element is the sender + each tracking's receieve
            # this way all history is generated
            passed = [r.assign_file.designation] + [t.receive_design for t in Tracking.objects.filter(file_id=r.assign_file)]
            # the last date the requisition was sent
            last_date = Tracking.objects.filter(file_id=r.assign_file).last().receive_date
            # map with readable titles from deslist
            passed = [deslist.get(str(d), d) for d in passed]
            req_history.append((r, passed, last_date))
        # in case there is no assignment, that means the history only contains the junior engg. 
        else:
            je = 'Civil_JE' if r.department == 'civil' else 'Electrical_JE'
            passed = [deslist[je]]
            req_history.append((r, passed, r.req_date))
    # sort based on last update, which is the element 2 in the 3-tuple
    req_history.sort(key=lambda t: t[2], reverse=True)
    # list of allowed actions filtered by designation
    for des in designations:
        if des.name == "DeanPnD":
            allowed_actions = ["Forward", "Revert", "Approve", "Reject"]
        elif des.name == "Director":
            allowed_actions = ["Revert", "Approve", "Reject"]
        elif des.name == "Electrical_JE" or des.name == "Civil_JE":
            allowed_actions = ["Forward", "Reject"]
        else:
            allowed_actions = ["Forward", "Revert", "Reject"]

    # Create context to render template
    context = {
            'files':files,
            'req':req,
            'incoming_files': incoming_files,
            'outgoing_files': outgoing_files,
            'assigned_req':assign_history,
            'desig':designations,
            'req_history': req_history,
            'allowed_actions': allowed_actions,
            'deslist': deslist,
    }
    return render(request, "officeModule/officeOfDeanPnD/officeOfDeanPnD.html", context)


@login_required
def submitRequest(request):
    """
        Endpoint used to create requisition
    """
    user = request.user
    extrainfo = ExtraInfo.objects.get(user=user)
    fdate = datetime.datetime.now().date()
    dept=request.POST.get('department')
    building = request.POST.get('building')
    title = request.POST.get('title')
    description = request.POST.get('description')

    request_obj = Requisitions(userid=extrainfo, req_date=fdate,
                               description=description, department=dept, title=title, building=building)
    request_obj.save()
    office_dean_PnD_notif(request.user, request.user, 'requisition_filed')

    # the cake is a lie
    context={}
    return HttpResponseRedirect("/office/officeOfDeanPnD#requisitions")


@login_required
def action(request):
    """
        Endpoint handling actions on assignment.
    """
    # deslist=['Civil_JE','Civil_AE','EE','DeanPnD','Electrical_JE','Electrical_AE']
    user = request.user
    extrainfo = ExtraInfo.objects.get(user=user)
    req_id=request.POST.get('req_id')
    requisition = Requisitions.objects.get(pk=req_id)
    description=request.POST.get('description')
    upload_file=request.FILES.get('estimate')
    track = Tracking.objects.filter(file_id=requisition.assign_file).filter(receiver_id=user).get(is_read=False)

    # current, previous and next Designation and HoldsDesignation found out
    current_design = track.receive_design
    current_hold_design = HoldsDesignation.objects.filter(user=user).get(designation=current_design)
    prev_design = track.current_design.designation
    prev_hold_design = track.current_design

    # This entire thing decides who is the next designation
    if current_design.name == "Civil_JE":
        next_hold_design = HoldsDesignation.objects.get(designation__name="Civil_AE")
    elif current_design.name == "Electrical_JE":
        next_hold_design = HoldsDesignation.objects.get(designation__name="Electrical_AE")
    elif current_design.name == "Civil_AE" or current_design.name == "Electrical_AE":
        next_hold_design = HoldsDesignation.objects.get(designation__name="EE")
    elif current_design.name == "EE":
        if requisition.building == "hostel":
            next_hold_design = HoldsDesignation.objects.get(designation__name="Dean_s")
        else:
            next_hold_design = HoldsDesignation.objects.get(designation__name="DeanPnD")
    elif current_design.name == "Dean_s":
        next_hold_design = HoldsDesignation.objects.get(designation__name="DeanPnD")
    # if estimate greater than 10 lacs, left to discretion of Dean PnD to forward when required
    elif "DeanPnD" in current_design.name: 
        next_hold_design = HoldsDesignation.objects.get(designation__name="Director")

    if 'Forward' in request.POST:
        Tracking.objects.create(
                file_id=requisition.assign_file,
                current_id=extrainfo,
                current_design=current_hold_design,
                receive_design=next_hold_design.designation,
                receiver_id=next_hold_design.working,
                remarks=description,
                upload_file=upload_file,
            )
        print("in forward, old track")
        print(vars(track))
        track.is_read = True
        track.save()
        office_dean_PnD_notif(request.user,next_hold_design.working, 'assignment_received')


    elif 'Revert' in request.POST:
        Tracking.objects.create(
                file_id=requisition.assign_file,
                current_id=extrainfo,
                current_design=current_hold_design,
                receive_design=prev_design,
                receiver_id=prev_hold_design.working,
                remarks=description,
                upload_file=upload_file,
            )
        print("in revert, old track")
        print(vars(track))
        track.is_read = True
        track.save()
        office_dean_PnD_notif(request.user,prev_hold_design.working, 'assignment_reverted')

    elif 'Reject' in request.POST:
        description = description + " This assignment has been rejected. No further changes to this assignment are possible. Please create new requisition if needed."
        Tracking.objects.create(
                file_id=requisition.assign_file,
                current_id=extrainfo,
                current_design=current_hold_design,
                receive_design=None,
                receiver_id=None,
                remarks=description,
                upload_file=upload_file,
                is_read = True,
            )
        track.is_read = True
        track.save()
        office_dean_PnD_notif(request.user,request.user, 'assignment_rejected')

    elif 'Approve' in request.POST:
        description = description + " This assignment has been approved. No further changes to this assignment are possible. Please create new requisition if needed."
        Tracking.objects.create(
                file_id=requisition.assign_file,
                current_id=extrainfo,
                current_design=current_hold_design,
                receive_design=None,
                receiver_id=None,
                remarks=description,
                upload_file=upload_file,
                is_read = True,
            )
        track.is_read = True
        track.save()
        office_dean_PnD_notif(request.user,request.user, 'assignment_approved')

    return HttpResponseRedirect("/office/officeOfDeanPnD/")


@login_required
def frequest(request):
    if request.method=='POST':
        form=Requisitionform(request.POST)
        print("hi")
    else:
        form=Requisitionform()

    return render(request,"officeModule/officeOfDeanPnD/viewRequisitions_content2.html",{'form':form})





def eisModulenew(request):
    project=Project_Registration.objects.all()
    project1=Project_Extension.objects.all()
    project2=Project_Closure.objects.all()
    project3=Project_Reallocation.objects.all()

    design = HoldsDesignation.objects.filter(working=request.user)
    print(design)
    desig=[]
    for i in design:
        desig.append(str(i.designation))

    context = {'project':project, 'project1':project1, 'project2':project2, 'project3':project3, 'desig':desig}

    return render(request, "eisModulenew/profile.html", context)



def officeOfPurchaseOfficr(request):
    return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html", {})

def admin_reject(request):
    if request.method == "POST":
        marked = request.POST.getlist("selected")

        return HttpResponse("Done!")


def officeOfRegistrar(request):
    view = registrar_create_doc.objects.all()
    view2 = registrar_director_section.objects.all()
    view3 = registrar_establishment_section.objects.all()
    view4 = apply_for_purchase.objects.all()
    view5 = quotations.objects.all()
    general= registrar_general_section.objects.all()
    current_date = datetime.datetime.now()

    context = {"view":view,"view2":view2,"view3":view3,"view4":view4,"view5":view5, "current_date":current_date,"general":general}

    return render(request, "officeModule/officeOfRegistrar/officeOfRegistrar.html", context)


def upload(request):
    print("asdasdasdasd")
    docname = request.POST.get("docname")
    purpose = request.POST.get("purpose")
    description = request.POST.get("description")
    file = request.FILES['upload']
    print(file)
    request = registrar_create_doc(file_name=docname, purpose=purpose, Description=description, file=file)
    request.save()
    print(request)
    return HttpResponseRedirect("/office/officeOfRegistrar/")


@login_required(login_url='/accounts/login')
def officeOfHOD(request):
    pro = Teaching_credits1.objects.filter(tag=0)
    pro1 = Assigned_Teaching_credits.objects.all()
    context = {'pro':pro,'pro1':pro1}
    return render(request, "officeModule/officeOfHOD/officeOfHOD.html", context)


@login_required
def project_register(request):
    user = request.user
    extrainfo = ExtraInfo.objects.get(user=user)
    project_title = request.POST.get('project_title')
    sponsored_agency=request.POST.get('sponsored_agency')
    CO_PI = request.POST.get('copi_name')
   # start_date = datetime.strptime(request.POST.get('start_date'), "%Y-%m-%d")
    start_date = request.POST.get('start_date')
    duration = request.POST.get('duration')
    #duration = datetime.timedelta('duration')
    agreement=request.POST.get('agreement')
    amount_sanctioned = request.POST.get('amount_sanctioned')
    project_type = request.POST.get('project_type')
    remarks=request.POST.get('remarks')
    #fund_recieved_date=datetime.strptime(request.POST.get('fund_recieved_date'), "%Y-%m-%d")
    project_operated = request.POST.get('project_operated')
    fund_recieved_date = request.POST.get('fund_recieved_date')

    request_obj = Project_Registration(PI_id=extrainfo, project_title=project_title,
                               sponsored_agency=sponsored_agency, CO_PI=CO_PI, agreement=agreement,
                               amount_sanctioned=amount_sanctioned, project_type=project_type,
                               remarks=remarks,duration=duration,fund_recieved_date=fund_recieved_date,start_date=start_date)
    request_obj.save()
    context={}
    return render(request,"eisModulenew/profile.html",context)

# Project Registration Table End.................................................................................

def project_registration_permission(request):
    if 'approve' in request.POST:
        id=request.POST.get('id')
        obj=Project_Registration.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Approve'
            obj.save()
    elif 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Registration.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Forward'
            obj.save()
    elif 'reject' in request.POST:
        id=request.POST.get('id')
        obj=Project_Registration.objects.get(pk=id)
        print(obj.DRSPC_response)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Disapprove'
            obj.save()
    return HttpResponseRedirect('/office/officeOfDeanRSPC/')


def project_extension_permission(request):
    if 'approve' in request.POST:
        id=request.POST.get('id')
        obj=Project_Extension.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Approve'
            obj.save()
    elif 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Extension.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Forward'
            obj.save()
    elif 'reject' in request.POST:
        id=request.POST.get('id')
        obj=Project_Extension.objects.get(pk=id)
        print(obj.DRSPC_response)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Disapprove'
            obj.save()
    return HttpResponseRedirect('/office/officeOfDeanRSPC/')


def project_closure_permission(request):
    if 'approve' in request.POST:
        id=request.POST.get('id')
        obj=Project_Closure.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            print("bb")
            obj.DRSPC_response='Approve'
            obj.save()
    elif 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Closure.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Forward'
            obj.save()
    elif 'reject' in request.POST:
        id=request.POST.get('id')
        obj=Project_Closure.objects.get(pk=id)
        print(obj.DRSPC_response)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Disapprove'
            obj.save()
    return HttpResponseRedirect('/office/officeOfDeanRSPC/')



def project_reallocation_permission(request):
    if 'approve' in request.POST:
        id=request.POST.get('id')
        obj=Project_Reallocation.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            print("aa")
            obj.DRSPC_response='Approve'
            obj.save()
    elif 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Reallocation.objects.get(pk=id)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Forward'
            obj.save()
    elif 'reject' in request.POST:
        id=request.POST.get('id')
        obj=Project_Reallocation.objects.get(pk=id)
        print(obj.DRSPC_response)
        if obj.DRSPC_response == 'Pending':
            obj.DRSPC_response='Disapprove'
            obj.save()
    return HttpResponseRedirect('/office/officeOfDeanRSPC/')



def hod_action(request):
    if 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Registration.objects.get(pk=id)
        print(obj.HOD_response)
        if obj.HOD_response == 'Pending' or obj.HOD_response == 'pending' :
            obj.HOD_response='Forwarded'
            obj.save()

    return HttpResponseRedirect('/office/eisModulenew/profile/')

def hod_closure(request):
    if 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Closure.objects.get(pk=id)
        print(obj.HOD_response)
        if obj.HOD_response == 'Pending' or obj.HOD_response == 'pending' :
            obj.HOD_response='Forwarded'
            obj.save()

    return HttpResponseRedirect('/office/eisModulenew/profile/')

def hod_extension(request):
    if 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Extension.objects.get(pk=id)
        print(obj.HOD_response)
        if obj.HOD_response == 'Pending' or obj.HOD_response == 'pending' :
            obj.HOD_response='Forwarded'
            obj.save()

    return HttpResponseRedirect('/office/eisModulenew/profile/')

def hod_allocation(request):
    if 'forward' in request.POST:
        id=request.POST.get('id')
        obj=Project_Reallocation.objects.get(pk=id)
        print(obj.HOD_response)
        if obj.HOD_response == 'Pending' or obj.HOD_response == 'pending' :
            obj.HOD_response='Forwarded'
            obj.save()

    return HttpResponseRedirect('/office/eisModulenew/profile/')



def pdf(request,pr_id):
    obj=Project_Registration.objects.get(pk=pr_id)
    return render(request,"officeModule/officeOfDeanRSPC/view_details.html",{"obj":obj})




def genericModule(request):
    context = {}
    return render(request, "officeModule/genericModule/genericModule.html", context)





# Project Closure Table Start .......................................................................................


def project_closure(request):
    project_id = request.POST.get('project_id')
    extrainfo1 = Project_Registration.objects.get(id=project_id)
   # ob = Project_Registration.objects.filter(id = extrainfo1)
    completion_date = request.POST.get('date')
   # extended_duration = ob.duration
    expenses_dues = request.POST.get('committed')
    expenses_dues_description = request.POST.get('remark1')
    payment_dues = request.POST.get('payment')
    payment_dues_description = request.POST.get('remark2')
    salary_dues = request.POST.get('salary')
    salary_dues_description = request.POST.get('remark3')
    advances_dues = request.POST.get('advance')
    advances_description = request.POST.get('remark4')
    others_dues = request.POST.get('other')
    other_dues_description = request.POST.get('remark5')
    overhead_deducted = request.POST.get('overhead')
    overhead_description = request.POST.get('remark6')

    request_obj1 = Project_Closure(project_id=extrainfo1, completion_date=completion_date,
                                    expenses_dues=expenses_dues,expenses_dues_description=expenses_dues_description,
                                    payment_dues=payment_dues,payment_dues_description=payment_dues_description,salary_dues=salary_dues,
                                    salary_dues_description=salary_dues_description,advances_dues=advances_dues,advances_description=advances_description,
                                    others_dues=others_dues,other_dues_description=other_dues_description,overhead_deducted=overhead_deducted,
                                    overhead_description=overhead_description)
    request_obj1.save()
    context={}
    return render(request,"eisModulenew/profile.html",context)



# PROJECT CLOSURE TABLE END HERE .......................................................................................






#PROJECT EXTENSION TABLE START ...........................................................................................



def project_extension(request):
    project_id = request.POST.get('project_id')
    ob = Project_Registration.objects.get(id=project_id)
    date = ob.start_date
    sponser = ob.sponsored_agency
    extended_duration =  request.POST.get('extended_duration')
    extension_detail = request.POST.get('extension_details')

    request_obj2 = Project_Extension(project_id=ob, date=date, extended_duration=extended_duration, extension_details= extension_detail)
    request_obj2.save()
    context={}
    return render(request,"eisModulenew/profile.html",context)


#PROJECT EXTENSION TABLE END ...........................................................................................


def project_reallocation(request):
    project_id = request.POST.get('project_id')
    ob1 = Project_Registration.objects.get(id=project_id)
    date =  request.POST.get('date')
    pfno =  request.POST.get('pfno')
    pbh =   request.POST.get('p_budget_head')
    p_amount =  request.POST.get('p_amount')
    nbh =  request.POST.get('n_budget_head')
    n_amount =  request.POST.get('n_amount')
    reason =  request.POST.get('reason')

    request_obj3 = Project_Reallocation(project_id=ob1, date=date, previous_budget_head=pbh,previous_amount=p_amount,
                                        new_budget_head=nbh,new_amount=n_amount,transfer_reason=reason,pf_no=pfno)
    request_obj3.save()
    print("sbhaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaabbbbhaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    context={}
    return render(request,"eisModulenew/profile.html",context)





@login_required
def teaching_form(request):
    roll_no=request.POST.get('roll_no')
    name=request.POST.get('name')
    programme=request.POST.get('programme')
    branch=request.POST.get('branch')
    course1=request.POST.get('course1')
    course2=request.POST.get('course2')
    course3=request.POST.get('course3')

    request_obj = Teaching_credits1(roll_no=roll_no,name=name, programme=programme, branch=branch,
                                     course1=course1, course2=course2, course3=course3)
    print("===================================================================")
    request_obj.save()
    context={}
    return render(request,"officeModule/officeOfHOD/tab4content4.html",context)

@login_required
def hod_work(request):
    roll_no=request.POST.get('roll_no')
    tc = Teaching_credits1.objects.get(roll_no=roll_no)
    assigned_course=request.POST.get('assigned_course')
    request_obj1 = Assigned_Teaching_credits(roll_no=tc,assigned_course=assigned_course)
    request_obj1.save()
    tc.tag=1
    tc.save()
    context={}
    return render(request,"officeModule/officeOfHOD/tab4content4.html",context)
    """return HttpResponseRedirect('')"""
    """return render(request,"officeModule/officeOfHOD/tab4content1.html",context)"""



def genericModule(request):
    context = {}

    return render(request, "ofricModule/genericModule.html", context)


@login_required
def apply_purchase(request):

    #
    # name=ExtraInfo.objects.get(user=user)

    # user = request.user
    # user = User.objects.get(id=1).extrainfo
    user=request.user.extrainfo
    # user=ExtraInfo.objects.get(id=user)

    if request.method == 'POST':
        '''if "submit" in request.POST:'''
        item_name=request.POST.get('item_name')
        quantity=request.POST.get('quantity')
        expected_cost=int(request.POST.get('expected_cost'))

        if  expected_cost >=25000 and expected_cost <= 250000 :
            local_comm_mem1_id=request.POST.get('local_comm_mem1_id')
            local_comm_mem2_id=request.POST.get('local_comm_mem2_id')
            local_comm_mem3_id=request.POST.get('local_comm_mem3_id')

        nature_of_item1= 1 if request.POST.get('nature_of_item1') == 'on' else 0
        nature_of_item2= 1 if request.POST.get('nature_of_item2') == 'on' else 0

        # extra = ExtraInfo.objects.all()
        # extraInfo = ExtraInfo.objects.get(id=inspecting_authority_id)

        purpose=request.POST.get('purpose')
        # budgetary_head_id=request.POST.get('budgetary_head_id')
        # inspecting_authority_id=request.POST.get('inspecting_authority_id')
        expected_purchase_date=request.POST.get('expected_purchase_date')
        # print(expected_purchase_date+"...........................")

    # xyz=apply_for_purchase(indentor_name=name,)
    # xyz.save()



        a = apply_for_purchase.objects.create(
                item_name=item_name,
                quantity=int(quantity),
                expected_cost=expected_cost,
                nature_of_item1=nature_of_item1,
                nature_of_item2=nature_of_item2,
                purpose=purpose,
                # budgetary_head_id = budgetary_head_id,
                # inspecting_authority_id=inspecting_authority_id,
                expected_purchase_date= expected_purchase_date,
                indentor_name=user,

        )
        a.save()
        if  expected_cost >=25000 and expected_cost <= 250000 :
            b = purchase_commitee.objects.create(

            local_comm_mem1_id=local_comm_mem1_id,
            local_comm_mem2_id=local_comm_mem2_id,
            local_comm_mem3_id=local_comm_mem3_id,
            )
            b.save()




        return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html",{})
    else:
        return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html",{})


def submit(request):
    context = {}

    return render(request, "officeModule/officeOfHOD/view_details.html", context)


@login_required
def after_purchase(request):
    if request.method == 'POST':
        '''if "submit" in request.POST:'''
        file_no=request.POST.get('file_no')
        amount=request.POST.get('amount')
        invoice=request.POST.get('invoice')
        apply_for_purchase.objects.filter(id=file_no).update(amount=amount, invoice=invoice)

        return render(request, "officeModule/officeOfPurchaseOfficer/after_purchase.html",{})
    else:
        return render(request, "officeModule/officeOfPurchaseOfficer/after_purchase.html",{})


@login_required
def officeOfPurchaseOfficer(request):
    context={}
    if request.method == 'POST':
        if "submit" in request.POST:
            vendor_name=request.POST['vendor_name']
            vendor_item=request.POST['vendor_item']
            vendor_address=request.POST['vendor_address']

            vendor.objects.create(
                vendor_name=vendor_name,
                vendor_item=vendor_item,
                vendor_address=vendor_address,
            )
            return HttpResponse("successflly added vendor")

        elif "store" in request.POST:
            item_type=request.POST.get('item_type')
            item_name=request.POST.get('item_name')
            quantity=request.POST.get('qunatity')

            stock.objects.create(
                item_type=item_type,
                item_name=item_name,
                quantity=quantity,
            )
            return HttpResponse("successflly added item")
        elif "item_search" in request.POST:
            srch = request.POST['item_name']
            match = stock.objects.filter(Q(item_name__icontains=srch))
            return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html",{'match':match})
        elif "vendor_search" in request.POST:
            sr = request.POST['item']
            matchv = vendor.objects.filter(Q(vendor_item__icontains=sr))
            return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html",{'matchv':matchv})
        elif "purchase_search" in request.POST:
            pr = request.POST['file']
            phmatch = apply_for_purchase.objects.filter(Q(id=pr))
            return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html",{'phmatch':phmatch})
        '''elif "delete_item" in request.POST:
            a = request.POST.getlist('box')
            for i in range(len(a)):
                k = stock.objects.get(id = a[i])
                k.delete()
            return HttpResponse("successflly deleted item")'''

    else:
        p=vendor.objects.all()
        q=stock.objects.all()
        ph=apply_for_purchase.objects.all()
    return render(request, "officeModule/officeOfPurchaseOfficer/officeOfPurchaseOfficer.html",{'p':p,'q':q,'ph':ph})

def delete_item(request,id):
    #template = 'officemodule/officeOfPurchaseOfficer/manageStore_content1.html'
    print(">>>>>>>")
    print(id)
    item = get_object_or_404(stock,id=id)
    item.delete()
    return HttpResponse("Deleted successfully")

def delete_vendor(request,id):
    #template = 'officemodule/officeOfPurchaseOfficerr/manageStore_content1.html'
    print(">>>>>>>")
    print(id)
    ven = get_object_or_404(vendor,id=id)
    ven.delete()
    return HttpResponse("Deleted successfully")

def edit_vendor(request,id):


    p= get_object_or_404(vendor,id=id)
    context={
        'p' : p
    }
    return render(request,"officeModule/officeOfPurchaseOfficer/edit.html",context)
    return HttpResponseRedirect('/office/officeOfPurchaseOfficer')

def edit(request):

    ID=request.POST.get('vendor_id')
    name=request.POST.get('vendor_name')
    item=request.POST.get('vendor_item')
    add=request.POST.get('vendor_address')
    d=vendor(id=ID,vendor_name=name,vendor_item=item,vendor_address=add)
    d.save()
    return HttpResponseRedirect('/office/officeOfPurchaseOfficer')

def edit_item(request,id):


    p= get_object_or_404(stock,id=id)
    context={
        'p' : p
    }
    return render(request,"officeModule/officeOfPurchaseOfficer/edit1.html",context)
    return HttpResponseRedirect('/office/officeOfPurchaseOfficer')

def edit1(request):

    ID=request.POST.get('item_id')
    name=request.POST.get('item_name')
    add=request.POST.get('quantity')
    d=stock(id=ID,item_name=name,quantity=add)
    d.save()
    return HttpResponseRedirect('/office/officeOfPurchaseOfficer')


def directorOffice(request):
     if request.user.is_authenticated:
        user_name=get_object_or_404(User,username=request.user.username)
        user=ExtraInfo.objects.all().filter(user=user_name).first()
        holds=HoldsDesignation.objects.filter(user=user.user)
        deslist1=['Director']
        if user.user_type == 'faculty': 
            context={ }
            return render(request, "officeModule/directorOffice/directorOffice.html", context)

#function gets the count of faculties department wise and top scoring students yearwise and department wise
def viewProfile(request):
    faculty = Faculty.objects.all()
    student = Student.objects.all()
    staff = Staff.objects.all()

    cs = Faculty.objects.all().filter(id__department__name = 'CSE').count()
    ec = Faculty.objects.all().filter(id__department__name = 'ECE').count()
    me = Faculty.objects.all().filter(id__department__name = 'ME').count()
    des = Faculty.objects.all().filter(id__department__name = 'DESIGN').count()
    ns = Faculty.objects.all().filter(id__department__name = 'NATURAL SCIENCE').count()
    #Top students of each year
    top_2017_cse = Student.objects.filter(id__id__startswith = '2017', id__department__name = 'CSE').order_by('-cpi')[:3]
    

    top_2016_cse = Student.objects.filter(id__id__startswith = '2016', id__department__name = 'CSE').order_by('-cpi')[:3]
    

    top_2015_cse = Student.objects.filter(id__id__startswith = '2015', id__department__name = 'CSE').order_by('-cpi')[:3]
    
    top_2017_me = Student.objects.filter(id__id__startswith = '2017', id__department__name = 'ME').order_by('-cpi')[:3]
    
    top_2016_me = Student.objects.filter(id__id__startswith = '2016', id__department__name = 'ME').order_by('-cpi')[:3]
    
    top_2015_me = Student.objects.filter(id__id__startswith = '2015', id__department__name = 'ME').order_by('-cpi')[:3]
    
    top_2017_ece = Student.objects.filter(id__id__startswith = '2017', id__department__name = 'ECE').order_by('-cpi')[:3]
   
    top_2016_ece = Student.objects.filter(id__id__startswith = '2016', id__department__name = 'ECE').order_by('-cpi')[:3]
    
    top_2015_ece = Student.objects.filter(id__id__startswith = '2015', id__department__name = 'ECE').order_by('-cpi')[:3]
    
    top_2017_design = Student.objects.filter(id__id__startswith = '2017', id__department__name = 'DESIGN').order_by('-cpi')[:3]
    
    top_2016_design = Student.objects.filter(id__id__startswith = '2016', id__department__name = 'DESIGN').order_by('-cpi')[:3]
    
    top_2015_design = Student.objects.filter(id__id__startswith = '2015', id__department__name = 'DESIGN').order_by('-cpi')[:3]
    
    all_counts = [cs,ec,me,des,ns]
    
    top_17_cse = []
    for x in top_2017_cse:
        top_17_cse.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_17_cse.append(x.cpi)

    top_17_ece = []
    for x in top_2017_ece:
        top_17_ece.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_17_ece.append(x.cpi)

    
    top_17_me = []
    for x in top_2017_me:
        top_17_me.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_17_me.append(x.cpi)

    top_17_design = []
    for x in top_2017_design:
        top_17_design.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_17_design.append(x.cpi)

    top_16_cse = []
    for x in top_2016_cse:
        top_16_cse.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_16_cse.append(x.cpi)

    top_16_ece = []
    for x in top_2016_ece:
        top_16_ece.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_16_ece.append(x.cpi)

    top_16_me = []
    for x in top_2016_me:
        top_16_me.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_16_me.append(x.cpi)

        top_16_design = []
    for x in top_2016_design:
        top_16_design.append(x.id.user.first_name + ' ' + x.id.user.last_name)  
        top_16_design.append(x.cpi)

    top_15_cse = []
    for x in top_2015_cse:
        top_15_cse.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_15_cse.append(x.cpi)

    top_15_ece = []
    for x in top_2015_ece:
        top_15_ece.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_15_ece.append(x.cpi)

    top_15_me = []
    for x in top_2015_me:
        top_15_me.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_15_me.append(x.cpi)

    top_15_design = []
    for x in top_2015_design:
        top_15_design.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        top_15_design.append(x.cpi)

    context={'all_counts':all_counts, 'top_17_cse': top_17_cse, 'top_16_cse': top_16_cse ,'top_15_cse': top_15_cse ,'top_17_ece': top_17_ece, 'top_16_ece': top_16_ece ,'top_15_ece': top_15_ece ,'top_17_me': top_17_me, 'top_16_me': top_16_me ,'top_15_me': top_15_me, 'top_17_design': top_17_design, 'top_16_design': top_16_design, 'top_15_design': top_15_design}
    #data = serializers.serialize('json', context)
    return JsonResponse(context)


# function for displaying projects under office module
def viewOngoingProjects(request):

    project = Project_Registration.objects.all()
    #title + type
    project_details = []

    for p in project:
        project_details.append(p.project_title)
        project_details.append(p.project_type)
        project_details.append(p.duration)
        project_details.append(p.sponsored_agency)
        project_details.append(p.HOD_response)

    print(project_details)

    context = {'project_details' : project_details} 
    return JsonResponse(context)     


# function for displaying Gymkhana office bearers
def viewOfficeBearers(request):
    club_info = Club_info.objects.all()
    club_details = []
    print(club_info)

    for c in club_info:
        club_details.append(c.club_name)
        club_details.append(c.category)
        club_details.append(c.co_ordinator.id.user.first_name + ' ' + c.co_ordinator.id.user.last_name)
        club_details.append(c.co_coordinator.id.user.first_name + ' ' + c.co_coordinator.id.user.last_name)
        club_details.append(c.faculty_incharge.id.user.first_name + ' ' + c.faculty_incharge.id.user.last_name)

    print(club_details)

    context = {'club_details': club_details}
    return JsonResponse(context)


#function for viewing the scheduled meetings
def viewMeetings(request):
    meeting_info=Meeting.objects.all()
    
    meeting = []
    

    for x in meeting_info:
        meeting.append(x.agenda)
        meeting.append(x.date)
        meeting.append(x.time)
        meeting.append(x.venue)
        #meeting.append(x.member)

    print(meeting)

    context = {
        'meeting':meeting 
    }    

    return JsonResponse(context)


# function for faculty information department wise 
def viewFacProfile(request):

    faculty = Faculty.objects.all()

    csfaculty = Faculty.objects.all().filter(id__department__name = 'CSE')
    ecefaculty = Faculty.objects.all().filter(id__department__name = 'ECE')
    mefaculty = Faculty.objects.all().filter(id__department__name = 'ME')
    desfaculty = Faculty.objects.all().filter(id__department__name = 'DESIGN')
    nsfaculty = Faculty.objects.all().filter(id__department__name = 'NATURAL SCIENCE')

    cse_faculty = []
    for x in csfaculty:
        cse_faculty.append(x.id.id)
        cse_faculty.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        cse_faculty.append(x.id.department.name)


    ece_faculty = []
    for x in ecefaculty:
        ece_faculty.append(x.id.id)
        ece_faculty.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        ece_faculty.append(x.id.department.name)


    me_faculty = []
    for x in mefaculty:
        me_faculty.append(x.id.id)
        me_faculty.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        me_faculty.append(x.id.department.name)


    ns_faculty = []
    for x in nsfaculty:
        ns_faculty.append(x.id.id)
        ns_faculty.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        ns_faculty.append(x.id.department.name)


    des_faculty = []
    for x in desfaculty:
        des_faculty.append(x.id.id)
        des_faculty.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        des_faculty.append(x.id.department.name)


    print(cse_faculty)

    context = {"cse_faculty": cse_faculty , "ece_faculty": ece_faculty , "me_faculty": me_faculty , "des_faculty": des_faculty , "ns_faculty": ns_faculty }

    return JsonResponse(context)


# function for staff information department wise 
def viewStaffProfile(request):

    staff_detail = Staff.objects.all()

    staff = []

    for x in staff_detail:
        staff.append(x.id.id)
        staff.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        staff.append(x.id.department.name)

    acad=Staff.objects.all().filter(Q(id__department__name='Academics') | Q(id__department__name='NATURAL SCIENCE') | Q(id__department__name='CSE')| Q(id__department__name='ECE')| Q(id__department__name='ME') | Q(id__department__name='DESIGN') | Q(id__department__name='MECHATRONICS') | Q(id__department__name='Workshop') | Q (id__department__name='Computer Centre') )

    academic = []
    for x in acad:
        academic.append(x.id.id)
        academic.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        academic.append(x.id.department.name)        


    admin = Staff.objects.all().filter(Q(id__department__name='General Administration') | Q(id__department__name='Finance and Accounts') |  Q(id__department__name='Purchase and Store') | Q(id__department__name='Registrar Office') | Q(id__department__name='Security and Central Mess') )

    administration = []

    for x in admin:
        administration.append(x.id.id)
        administration.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        administration.append(x.id.department.name)


    place =  Staff.objects.all().filter(Q(id__department__name='Placement Cell') )    
    placement = []
    for x in place:
        placement.append(x.id.id)
        placement.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        placement.append(x.id.department.name)  


    offc=Staff.objects.all().filter(Q(id__department__name='Student Affairs') | Q(id__department__name='Office of The Dean P&D') | Q(id__department__name='Directorate') | Q(id__department__name='Office of The Dean R&D')  )
    office =[] 
    for x in offc:
        office.append(x.id.id)
        office.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        office.append(x.id.department.name)  

    other=Staff.objects.all().filter(Q(id__department__name='Establishment & P&S') | Q(id__department__name='IWD') | Q(id__department__name='F&A & GA') | Q(id__department__name='Establishment, RTI and Rajbhasha') | Q(id__department__name='Establishment')  )
    others =[]
    for x in other:
        others.append(x.id.id)
        others.append(x.id.user.first_name + ' ' + x.id.user.last_name)
        others.append(x.id.department.name)  


    context = {"staff": staff, "academic":academic,"administration":administration , "placement": placement , "office": office , "others":others }

    return JsonResponse(context)


# function for student information based on entered programme, batch and department
def viewStudentProfile(request):

    print("in the function")

    student = Student.objects.all()

    student_detail=[]

    studentsearch = " "

    if request.is_ajax():
        year = request.GET.get('year')
        programme = request.GET.get('programme')
        department = request.GET.get('department')
        #studentsearch = Student.objects.all().filter(id__id__startswith).(programme=prog , id__department__name=dep )
        #print("in here we are")
        print(year)
        print(programme)
        print(department)
        #last two letters of 'year' variable
        yr = year[2:4]
        print(yr)
        if programme in ('M.Tech','M.Des','PhD'):
            studentsearch = Student.objects.all().filter(id__id__startswith = yr, id__department__name = department ).filter(programme=programme)
        else:
            studentsearch = Student.objects.all().filter(id__id__startswith = year, programme = programme, id__department__name = department)
            
        print(studentsearch)
        
        for x in studentsearch:
            student_detail.append(x.id.id)
            student_detail.append(x.id.user.first_name + ' ' + x.id.user.last_name)
            student_detail.append(x.id.department.name)
            student_detail.append(x.cpi)

        info =[]
        info.append(programme) 
        info.append(year) 
        info.append(department)  
                
     
        context = { "student_detail":student_detail , "info":info} #, 'year':year, 'prog': prog, 'dep': dep}
        return JsonResponse(context)


#function for scheduling a meeting with faculties
def meeting(request):
    agenda = request.POST['agenda']
    venue = request.POST['venue']
    adate = request.POST['adate']
    meeting_time = request.POST['meeting_time']
    fetched_members = request.POST.getlist('member')

    members = [] 
    for i in fetched_members: 
        if i not in members: 
            members.append(i)

    print(len(members))
    print(len(fetched_members))

    if(len(members) != len(fetched_members)):
        print("in if")
        return HttpResponse('Error handler content', status=400)
    
    else:
        print("inside else")
        Meeting.objects.create(
            agenda=agenda,
            time = meeting_time,
            date = adate,
            venue = venue
        )

        meeting_id = Meeting.objects.get(agenda=agenda,time= meeting_time,venue=venue,date=adate)    
        for x in members:
            splitted_name = str(x).split(' ')
            u = User.objects.get(first_name = splitted_name[0], last_name = splitted_name[1])
            e = ExtraInfo.objects.get(user = u.id)
            f = Faculty.objects.get(id = e.id)
            Member.objects.create(
                meeting_id=meeting_id,
                member_id=f
            ) 
        

    return HttpResponse("success")

#function to fill the dropdown choices of faculty in meeting form
def meeting_dropdown(request):
    if request.is_ajax():
        fac = Faculty.objects.all();
        faculty =[]
        for x in fac:
            faculty.append(x.id.user.first_name + ' ' + x.id.user.last_name)

        context = {'faculty':faculty}
        return JsonResponse(context)


#function for viewing and canceling the scheduled meetings
def planMeetings(request):
    meeting_id = request.POST.getlist('list')
    print("inside delete")
    print(meeting_id)
    for z in meeting_id:
        Meeting.objects.filter(id=z).delete()
        Member.objects.filter(meeting_id=z).delete()

    meeting_info=Meeting.objects.all()

    meeting = []

    for x in meeting_info:
        meeting.append(x.id)
        meeting.append(x.agenda)
        meeting.append(x.date)
        meeting.append(x.time)
        meeting.append(x.venue)
        Members = Member.objects.all().filter(meeting_id=x.id)
        members = []
        for y in Members:
            members.append(y.member_id.id.user.first_name + ' ' + y.member_id.id.user.last_name)
        meeting.append(members)
    
    print(meeting)

    context = {
        'meeting':meeting 
    }    

    return JsonResponse(context)





#function for displaying HODs of different departments
def viewHOD(request):
    #designation name has been used as is stored in database
    cse_hod = HoldsDesignation.objects.all().filter(designation__name="CSE HOD")
    ece_hod = HoldsDesignation.objects.all().filter(designation__name="HOD (ECE)")
    me_hod = HoldsDesignation.objects.all().filter(designation__name="HOD (ME)")
    ns_hod = HoldsDesignation.objects.all().filter(designation__name="HOD (NS)")
    des_hod = HoldsDesignation.objects.all().filter(designation__name="HOD (DESIGN)")

    print("inside hod")

    csehod=[]

    for c in cse_hod:
        csehod.append(c.user.first_name + ' ' + c.user.last_name)

    ecehod=[]

    for e in ece_hod:
        ecehod.append(e.user.first_name + ' ' + e.user.last_name)

    mehod=[]

    for m in me_hod:
        mehod.append(m.user.first_name + ' ' + m.user.last_name)

    nshod=[]

    for n in ns_hod:
        nshod.append(n.user.first_name + ' ' + n.user.last_name)


    deshod=[]

    for d in des_hod:
        deshod.append(d.user.first_name + ' ' + d.user.last_name)

    context = {'csehod':csehod, 'ecehod':ecehod, 'mehod':mehod, 'nshod': nshod, 'deshod':deshod}
    #data=serializers.serialize('json', context)

    return JsonResponse(context)



def appoint(request):
    print('in there')

    purpose = request.POST.get('purpose')
    venue = request.POST.get('venue')
    adate = request.POST.get('adate')
    adate = adate.replace(",", "")

    print(adate)
    adate = str(datetime.datetime.strptime(adate, '%B %d %Y'))[:10]
    print(adate)
    # if (adate==""):
    #     adate = None
    # print(datetime.date.today())
    member = request.POST.get('member')
    print(purpose, venue, adate, member)
    print('here 1')
    meetobj = Meeting(venue=venue, agenda=purpose, date=adate)
    meetobj.save()
    print('here 2')
    user = User.objects.get(username=member)
    info = ExtraInfo.objects.get(user=user)
    mem = Faculty.objects.get(id=info)
    print('here 3')
    print(mem)
    # meeting = Meeting.objects.get(id=meetobj.id)
    # print(meeting)
    appointobj = Member(member_id=mem, meeting_id=meetobj)
    print(appointobj)
    appointobj.save()

    return HttpResponseRedirect("/office/directorOffice/")




def profile(request):
    facult = request.POST.get('faculty')
    faculty = Faculty.objects.get(id=facult)
    # Id=request.POST.get('id')
    #    member=request.POST.get('member')
    #    Designation=request.POST.get('designation')
    #    Department=request.POST.get('dept')
    #    print(Id,member,Designation,Department)
    #    user = User.objects.get(username=member)
    #    info = ExtraInfo.objects.get(user=user)
    #    mem = Faculty.objects.get(id = info)

    return HttpResponseRedirect("/office/directorOffice/")


def officeOfDeanAcademics(request):
    student=Student.objects.all();
    instructor=Instructor.objects.all();
    spi=Spi.objects.all();
    grades=Grades.objects.all();
    course=Course.objects.all();
    thesis=Thesis.objects.all();
    minutes=Meeting.objects.all().filter(minutes_file="");
    final_minutes=Meeting.objects.all().exclude(minutes_file="");
    hall_allotment=hostel_allotment.objects.all();
    assistantship=Assistantship.objects.all();
    mcm=Mcm.objects.all();
    designation = HoldsDesignation.objects.all().filter(working=request.user)
    all_designation=[]
    for i in designation:
        all_designation.append(str(i.designation))




    context = {'student':student,
                'instructor':instructor,
                'assistantship':assistantship,
                #'hall': Constants.HALL_NO,
                'hall_allotment':hall_allotment,
                'mcm':mcm,
                'thesis':thesis,
                'meetingMinutes':minutes,
                'final_minutes':final_minutes,
                'all_desig':all_designation,}

    return render(request, "officeModule/officeOfDeanAcademics/officeOfDeanAcademics.html", context)

def assistantship(request):
    # print(request.POST.getlist('check'))
    ob=Assistantship.objects.all()
    # print(id[0])
    context = {'ob':ob}
    return HttpResponseRedirect('/office/officeOfDeanAcademics')


def init_assistantship(request):
    title= request.POST.get('title')
    date = request.POST.get('date')
    Time = request.POST.get('time')
    Venue = request.POST.get('venue')
    Agenda = request.POST.get('Agenda')
    p=Meeting(title=title,venue=Venue,date=date,time=Time,agenda=Agenda);
    p.save()
    return HttpResponseRedirect('/office/officeOfDeanAcademics')

def scholarshipform(request):
    file=request.FILES['hostel_file']
    hall_no=request.POST.get('hall_no')
    #description= request.POST.get('description')
    p=hostel_allotment(allotment_file=file,hall_no=hall_no)
    p.save()
    return HttpResponseRedirect('/office/officeOfDeanAcademics')

def formsubmit(request):
    a = request.POST.get('example');
    comment = request.POST.get('comment');
    obj = Assistantship.objects.get(pk=a)
    if "approve" in request.POST:
        obj.action=1
        obj.comments=comment
        obj.save()
    elif "reject" in request.POST:
        obj.action=2
        obj.comments=comment
        obj.save()

    return HttpResponseRedirect('/office/officeOfDeanAcademics')



    # elif "reject" in request.POST:

def scholarship(request):

    return HttpResponse('')

def courses(request):

    return HttpResponse('')

def applications(request):

    return HttpResponse('')

def semresults(request):

    return HttpResponse('')

def thesis(request):

    return HttpResponse('')
