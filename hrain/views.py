from django.shortcuts import render_to_response
from django.template import RequestContext
from enhydris.hrain import models

def index(request):
    eventgroups = []
    year = 0
    for e in models.Event.objects.all():
        if e.start_date.year != year:
            year = e.start_date.year
            eventgroups.append({ 'year': year, 'events': [] })
        eventgroups[-1]['events'].append(e)
    return render_to_response('rain-index.html',
                                    { 'eventgroups': eventgroups },
                                    context_instance=RequestContext(request))

def event(request):
    pass
