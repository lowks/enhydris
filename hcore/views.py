from __future__ import with_statement 
import calendar
import json
import math
import mimetypes
import os
import linecache
from calendar import monthrange
from datetime import timedelta, datetime
from tempfile import mkstemp
import django.db
from pthelma.timeseries import Timeseries as TTimeseries
from pthelma.timeseries import datetime_from_iso
from string import lower
from django.http import (HttpResponse, HttpResponseRedirect,
                            HttpResponseForbidden, Http404)
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.views.generic import list_detail
from django.views.generic.create_update import create_object
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.views import login as auth_login
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.shortcuts import render_to_kml
from django.contrib.gis.geos import Polygon
from django.contrib import messages
from django.conf import settings
from django.db.models import Q
from django.core.servers.basehttp import FileWrapper
from django.core.urlresolvers import reverse
from django.utils import simplejson
from django.utils.html import escape
from django.utils.translation import ugettext_lazy as _
from django.db.models import Count
from enhydris.hcore.models import *
from enhydris.hcore.decorators import *
from enhydris.hcore.forms import *
from enhydris.hcore.tstmpupd import update_ts_temp_file

####################################################
# VIEWS

def login(request, *args, **kwargs):
    if request.user.is_authenticated():
        redir_url = request.GET.get('next', reverse('index'))
        messages.info(request, 'You are already logged on; '
                               'logout to log in again.')
        return HttpResponseRedirect(redir_url)
    else:
        return auth_login(request, *args, **kwargs)

def index(request):
    return render_to_response('index.html', {},
        context_instance=RequestContext(request))


def protect_gentityfile(request):
    """
    This view is used to disallow users to be able to browse through the
    uploaded gentity files which is the default behaviour of django.
    """
    raise Http404

def station_detail(request, *args, **kwargs):
    anonymous_can_download_data = False
    if hasattr(settings, 'TSDATA_AVAILABLE_FOR_ANONYMOUS_USERS') and\
            settings.TSDATA_AVAILABLE_FOR_ANONYMOUS_USERS:
        anonymous_can_download_data = True
    display_copyright = hasattr(settings, 'DISPLAY_COPYRIGHT_INFO') and\
        settings.DISPLAY_COPYRIGHT_INFO
    stat = get_object_or_404(Station, pk=kwargs["object_id"])
    owner = stat.owner
    chart_exists = False
    if hasattr(settings, 'INSTALLED_APPS'):
        if 'enhydris.hchartpages' in settings.INSTALLED_APPS:
            from enhydris.hchartpages.models import ChartPage
            chart_exists = ChartPage.objects.filter(url_int_alias=stat.id).exists()
    use_open_layers = settings.USE_OPEN_LAYERS and\
                      stat.srid and stat.point
    kwargs["extra_context"] = {"owner":owner,
        "enabled_user_content":settings.USERS_CAN_ADD_CONTENT,
        "use_open_layers": use_open_layers,
        "anonymous_can_download_data": anonymous_can_download_data,
        "display_copyright": display_copyright,
        "chart_exists": chart_exists}
    kwargs["request"] = request
    kwargs["template_name"] = "station_detail.html"
    return list_detail.object_detail(*args, **kwargs)

def station_brief(request, object_id):
    station_objects = Station.objects.all()
    if len(settings.SITE_STATION_FILTER)>0:
        station_objects = station_objects.filter(**settings.SITE_STATION_FILTER)
    return list_detail.object_detail(request,
                                     queryset=station_objects,
                                     object_id = object_id,
                                     template_object_name = "station",
                                     template_name = "station_brief.html")

def get_search_query(search_terms):
    query = Q()
    for term in search_terms:
        query &= (Q(name__icontains=term) | Q(name_alt__icontains=term) |
                  Q(short_name__icontains=term )|
                  Q(short_name_alt__icontains=term) |
                  Q(remarks__icontains=term) |
                  Q(remarks_alt__icontains=term)|
                  Q(water_basin__name__icontains=term) |
                  Q(water_basin__name_alt__icontains=term) |
                  Q(water_division__name__icontains=term) |
                  Q(water_division__name_alt__icontains=term) |
                  Q(political_division__name__icontains=term) |
                  Q(political_division__name_alt__icontains=term) |
                  Q(type__descr__icontains=term) |
                  Q(type__descr_alt__icontains=term) |
                  Q(owner__organization__name__icontains=term) |
                  Q(owner__person__first_name__icontains=term) |
                  Q(owner__person__last_name__icontains=term))
    return query

_station_list_csv_headers = ['id', 'Name', 'Alternative name', 'Short name',
    'Alt short name', 'Type', 'Owner', 'Start date', 'End date', 'Abscissa',
    'Ordinate', 'SRID', 'Approximate', 'Altitude', 'SRID', 'Water basin',
    'Water division', 'Political division', 'Active', 'Automatic', 'Remarks',
    'Alternative remarks', 'Last modified']

def _station_csv(s):
    abscissa, ordinate = s.point.transform(s.srid, clone=True) if s.point else (None, None)
    return [unicode(x).encode('utf-8') for x in
           [s.id, s.name, s.name_alt, s.short_name, s.short_name_alt,
            s.type.descr if s.type else "", s.owner, s.start_date, s.end_date,
            abscissa, ordinate, s.srid, s.approximate, s.altitude, s.asrid,
            s.water_basin.name if s.water_basin else "",
            s.water_division.name if s.water_division else "",
            s.political_division.name if s.political_division else "",
            s.is_active, s.is_automatic, s.remarks, s.remarks_alt,
            s.last_modified]
           ]

_instrument_list_csv_headers = ['id', 'Station', 'Type', 'Name',
    'Alternative name', 'Manufacturer', 'Model', 'Start date', 'End date',
    'Active', 'Remarks', 'Alternative remarks']

def _instrument_csv(i):
    return [unicode(x).encode('utf-8') for x in
           [i.id, i.station.id, i.type.descr if i.type else "", i.name,
            i.name_alt, i.manufacturer, i.model, i.start_date, i.end_date,
            i.is_active, i.remarks, i.remarks_alt]
           ]

_timeseries_list_csv_headers = ['id', 'Station', 'Instrument', 'Variable',
    'Unit', 'Name', 'Alternative name', 'Precision', 'Time zone', 'Time step',
    'Nom. Offs. Min.', 'Nom. Offs. Mon.', 'Act. Offs. Min.',
    'Act. Offs.  Mon.', 'Remarks', 'Alternative Remarks']

def _timeseries_csv(t):
    return [unicode(x).encode('utf-8') for x in
           [t.id, t.gentity.id, t.instrument.id if t.instrument else "",
            t.variable.descr if t.variable else "",
            t.unit_of_measurement.symbol, t.name, t.name_alt, t.precision,
            t.time_zone.code, t.time_step.descr if t.time_step else "",
            t.nominal_offset_minutes, t.nominal_offset_months,
            t.actual_offset_minutes, t.actual_offset_months]
           ]

def _prepare_csv(queryset):
    import tempfile, csv, os, os.path
    from zipfile import ZipFile, ZIP_DEFLATED
    tempdir = tempfile.mkdtemp()
    zipfilename = os.path.join(tempdir, 'data.zip')
    zipfile = ZipFile(zipfilename, 'w', ZIP_DEFLATED)

    stationsfilename = os.path.join(tempdir, 'stations.csv')
    stationsfile = open(stationsfilename, 'w')
    try:
        csvwriter = csv.writer(stationsfile)
        csvwriter.writerow(_station_list_csv_headers)
        for station in queryset:
            csvwriter.writerow(_station_csv(station))
    finally:
        stationsfile.close()
    zipfile.write(stationsfilename, 'stations.csv')

    instrumentsfilename = os.path.join(tempdir, 'instruments.csv')
    instrumentsfile = open(instrumentsfilename, 'w')
    try:
        csvwriter = csv.writer(instrumentsfile)
        csvwriter.writerow(_instrument_list_csv_headers)
        for station in queryset:
            for instrument in station.instrument_set.all():
                csvwriter.writerow(_instrument_csv(instrument))
    finally:
        instrumentsfile.close()
    zipfile.write(instrumentsfilename, 'instruments.csv')

    timeseriesfilename = os.path.join(tempdir, 'timeseries.csv')
    timeseriesfile = open(timeseriesfilename, 'w')
    try:
        csvwriter = csv.writer(timeseriesfile)
        csvwriter.writerow(_timeseries_list_csv_headers)
        for station in queryset:
            for timeseries in station.timeseries.order_by('instrument__id'):
                csvwriter.writerow(_timeseries_csv(timeseries))
    finally:
        timeseriesfile.close()
    zipfile.write(timeseriesfilename, 'timeseries.csv')

    import textwrap
    readmefilename = os.path.join(tempdir, 'README')
    readmefile = open(readmefilename, 'w')
    readmefile.write(textwrap.dedent("""\
        The functionality which provides you with CSV versions of the station,
        instrument and time series list is a quick way to enable HUMANS to
        examine these lists with tools such as spreadsheets. It is not
        intended to be used by any automation tools: headings, columns, file
        structure and everything is subject to change without notice.

        If you are a developer and need to write automation tools, do not rely
        on the CSV files. Instead, use the documented API
        (http://openmeteo.org/doc/api.html), or contact us (the Enhydris
        developers, not the web site maintainers) and insist that we support
        one of these open standards appropriate for such information
        interchange.
        """))
    readmefile.close()
    zipfile.write(readmefilename, 'README')

    zipfile.close()
    os.remove(stationsfilename)
    os.remove(instrumentsfilename)
    os.remove(timeseriesfilename)
    os.remove(readmefilename)

    return zipfilename
    
#FIXME: Now you must keep the "political_division" FIRST in order
@filter_by(('political_division','owner', 'type', 'water_basin',
            'water_division','variable','bounded',))
@sort_by
def station_list(request, queryset, *args, **kwargs):

    kwargs["extra_context"] = {
        "use_open_layers": settings.USE_OPEN_LAYERS,
        # The following is a hack because enhydris.sorting (aka
        # django-sorting) sucks. I18N should be in the template, not
        # here (but anyway the whole list needs revising, manual
        # selecting of visible columns, reordering of columns, etc.)
        "id_heading": _("id"),
        "name_heading": _("Name"),
        "water_basin_heading": _("Water basin"),
        "water_division_heading": _("Water division"),
        "political_division_heading": _("Political division"),
        "owner_heading": _("Owner"),
        "type_heading": _("Type"),
    }
    kwargs["template_name"] = "station_list.html"
    if request.GET.has_key("ts_only") and request.GET["ts_only"]=="True":
        tmpset = queryset.annotate(tsnum=Count('timeseries'))
        queryset = tmpset.exclude(tsnum=0)

    if request.GET.has_key("check") and request.GET["check"]=="search":
        # The case we got a simple search request
        kwargs["extra_context"].update({"search":True})
        query_string = request.GET.get('q', "")
        search_terms = query_string.split()
        results = queryset

        if search_terms:
            results = results.filter(get_search_query(search_terms)).distinct()
            queryset = results
        else:
            results = []
        kwargs["extra_context"].update({'query': query_string,
                                        'terms': search_terms, })
    else:
        if len(request.GET.items())>0:
            kwargs["extra_context"].update({"advanced_search":True})

    if hasattr(settings, 'USERS_CAN_ADD_CONTENT'):
        if settings.USERS_CAN_ADD_CONTENT:
            kwargs["extra_context"].update({'enabled_user_content':
                                    settings.USERS_CAN_ADD_CONTENT})

    if request.GET.get("format", "").lower()=="csv":
        import os.path
        zipfilename = _prepare_csv(queryset)
        response = HttpResponse(file(zipfilename, 'rb').read(),
                                        content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename=data.zip'
        response['Content-Length'] = str(os.path.getsize(zipfilename))
        return response

    return list_detail.object_list(request,queryset=queryset, *args, **kwargs )


def bufcount(filename):
    lines = 0
    with open(filename) as f:
        buf_size = 1024 * 1024
        read_f = f.read # loop optimization
        buf = read_f(buf_size)
        while buf:
            lines += buf.count('\n')
            buf = read_f(buf_size)
    return lines

def inc_month(adate, months):
    y = adate.year
    m = adate.month+months
    if m>12: (y, m)=(y+1, m-12)
    if m<1: (y, m)=(y-1, m+12)
    d = min(adate.day, monthrange(y, m)[1])
    return adate.replace(year=y, month=m, day=d)

def timeseries_data(request, *args, **kwargs):

    def date_at_pos(pos):
        s = linecache.getline(afilename, pos)
        return datetime_from_iso(s.split(',')[0])

    def timedeltadivide(a, b):
        """Divide timedelta a by timedelta b."""
        a = a.days*86400+a.seconds
        b = b.days*86400+b.seconds
        return float(a)/float(b)

# Return the nearest record number to the specified date
# The second argument is 0 for exact match, -1 if no
# exact match and the date is after the record found,
# 1 if no exact match and the date is before the record.
    def find_line_at_date(adatetime, totlines):
        if totlines <2:
            return totlines
        i1, i2 = 1, totlines
        d1=date_at_pos(i1)
        d2=date_at_pos(i2)
        if adatetime<=d1:
            return (i1, 0 if d1==adatetime else 1)
        if adatetime>=d2:
            return (i2, 0 if d2==adatetime else -1)
        while(True):
            i = i1 + int(round( float(i2-i1)* timedeltadivide( adatetime-d1, d2-d1) ))
            d = date_at_pos(i)
            if d==adatetime: return (i, 0)
            if (i==i1) or (i==i2): return (i, -1 if i==i1 else 1)
            if d<adatetime:
                d1, i1 = d, i
            if d>adatetime:
                d2, i2 = d, i

    def add_to_stats(date, value):
        if not gstats['max']:
            gstats['max'] = value
            gstats['min'] = value
            gstats['sum'] = 0
            gstats['vsum'] = [0.0, 0.0]
            gstats['count'] = 0
            gstats['vectors'] = [0]*8
        if value>=gstats['max']:
            gstats['max'] = value
            gstats['max_tstmp'] = date
        if value<=gstats['min']:
            gstats['min'] = value
            gstats['min_tstmp'] = date
        if is_vector:
            value2 = value
            if value2>=360: value2-=360
            if value2<0: value2+=360
            if value2<0 or value2>360: return
            # reversed order of x, y since atan2 definition is
            # math.atan2(y, x)
            gstats['vsum'][1]+=math.cos(value2*math.pi/180)
            gstats['vsum'][0]+=math.sin(value2*math.pi/180)
            value2 = value2+22.5 if value2<337.5 else value2-337.5
            gstats['vectors'][int(value2/45)]+=1
        gstats['sum']+= value
        gstats['last'] = value
        gstats['last_tstmp'] = date
        gstats['count']+=1
            
    def inc_datetime(adate, unit, steps):
        if unit=='day':
            return adate+steps*timedelta(days=1)
        elif unit=='week':
            return adate+steps*timedelta(weeks=1)
        elif unit=='month':
            return inc_month(adate, steps)
        elif unit=='year':
            return inc_month(adate, 12*steps)
        elif unit=='moment':
            return adate            
        elif unit=='hour':
            return adate+steps*timedelta(minutes=60)
        elif unit=='twohour':
            return adate+steps*timedelta(minutes=120)
        else: raise Http404
   

    if hasattr(settings, 'TS_GRAPH_BIG_STEP_DENOMINATOR'):
        step_denom = settings.TS_GRAPH_BIG_STEP_DENOMINATOR
    else:
        step_denom = 200
    if hasattr(settings, 'TS_GRAPH_FINE_STEP_DENOMINATOR'):
        fine_step_denom = settings.TS_GRAPH_FINE_STEP_DENOMINATOR
    else:
        fine_step_denom = 50
    if hasattr(settings, 'TS_GRAPH_CACHE_DIR'):
        cache_dir = settings.TS_GRAPH_CACHE_DIR
    else:
        cache_dir = '/var/tmp/enhydris-timeseries/'
    if request.method == "GET" and request.GET.has_key('object_id'):
        response = HttpResponse(content_type='application/json')
        response.status_code = 200
        object_id = request.GET['object_id']
        afilename = cache_dir+'%d.hts'%int(object_id)
        update_ts_temp_file(cache_dir, django.db.connection, object_id)
        chart_data = []
        if request.GET.has_key('start_pos') and request.GET.has_key('end_pos'):
            start_pos = int(request.GET['start_pos'])
            end_pos = int(request.GET['end_pos'])
        else:
            end_pos = bufcount(afilename)
            tot_lines = end_pos
            if request.GET.has_key('last'):
                if request.GET.has_key('date') and request.GET['date']:
                    datetimestr = request.GET['date']
                    datetimefmt = '%Y-%m-%d'
                    if request.GET.has_key('time') and request.GET['time']:
                        datetimestr = datetimestr + ' '+request.GET['time']
                        datetimefmt = datetimefmt + ' %H:%M'
                    try:
                        first_date = datetime.strptime(datetimestr, datetimefmt)
                        last_date = inc_datetime(first_date, request.GET['last'], 1)
                        (end_pos, is_exact) = find_line_at_date(last_date, tot_lines)
                        if request.GET.has_key('exact_datetime'):
                            if request.GET['exact_datetime'] == 'true':
                                if is_exact!=0:
                                    raise Http404
                    except ValueError:
                        raise Http404
                else:
                    last_date = date_at_pos(end_pos)
                    first_date = inc_datetime(last_date, request.GET['last'], -1)
# This is an almost bad workarround to exclude the first record from
# sums, i.e. when we need the 144 10 minute values from a day.
                    if request.GET.has_key('start_offset'):
                        offset = float(request.GET['start_offset'])
                        first_date+= timedelta(minutes=offset)
                start_pos= find_line_at_date(first_date, tot_lines)[0]
            else:
                start_pos= 1
        length = end_pos - start_pos + 1
        step = int(length/step_denom) or 1
        fine_step= int(step/fine_step_denom) or 1
        if not step%fine_step==0:
            step = fine_step * fine_step_denom
        pos=start_pos
        amax=''
        prev_pos=-1
        tick_pos=-1
        is_vector = request.GET.has_key('vector') and request.GET['vector'] == 'true'
        gstats = {'max': None, 'min': None, 'count': 0,
                       'max_tstmp': None, 'min_tstmp': None,
                       'sum': None, 'avg': None,
                       'vsum': None, 'vavg': None,
                       'last': None, 'last_tstmp': None, 
                       'vectors': None}
        afloat = 0.01
        try:
            linecache.checkcache(afilename)
            while pos < start_pos+length:
                s = linecache.getline(afilename, pos)
                if s.isspace():
                    pos+=fine_step
                    continue 
                t = s.split(',') 
# Use the following exception handling to catch incoplete
# reads from cache. Tries only one time, next time if
# the error on the same line persists, it raises.
                try:
                    k = datetime_from_iso(t[0])
                    v = t[1]
                except:
                    if pos>prev_pos:
                        prev_pos = pos
                        linecache.checkcache(afilename)
                        continue
                    else:
                        raise
                if v!='':
                    afloat = float(v)
                    add_to_stats(k, afloat)
                    if amax=='':
                        amax = afloat
                    else:
                        amax = afloat if afloat>amax else amax 
                if (pos-start_pos)%step==0:
                    tick_pos=pos
                    if amax == '': amax = 'null'
                    chart_data.append([calendar.timegm(k.timetuple())*1000, str(amax), pos])
                    amax = ''
# Some times linecache tries to read a file being written (from 
# timeseries.write_file). So every 5000 lines refresh the cache.
                if (pos-start_pos)%5000==0:
                    linecache.checkcache(afilename)
                pos+=fine_step
            if length>0 and tick_pos<end_pos:
                if amax == '': amax = 'null'
                chart_data[-1]=[calendar.timegm(k.timetuple())*1000, str(amax), end_pos]
        finally:
            linecache.clearcache()
        if chart_data:
            if gstats['count']>0:
                gstats['avg'] = gstats['sum'] / gstats['count']
                if is_vector:
                    gstats['vavg']=math.atan2(*gstats['vsum'])*180/math.pi
                    if gstats['vavg']<0: 
                        gstats['vavg']+=360 
                for item in ('max_tstmp', 'min_tstmp', 'last_tstmp'):
                    gstats[item] = calendar.timegm(gstats[item].timetuple())*1000
            response.content = json.dumps({'data': chart_data, 'stats': gstats})
        else:
            response.content = json.dumps("")
        callback = request.GET.get("jsoncallback", None)    
        if callback:
            response.content = '%s(%s)'%(callback, response.content,)
        return response
    else:
        raise Http404

def timeseries_detail(request, queryset, object_id, *args, **kwargs):
    """Return the details for a specific timeseries object."""

    enabled_user_content = False
    if hasattr(settings, 'USERS_CAN_ADD_CONTENT'):
        if settings.USERS_CAN_ADD_CONTENT:
            enabled_user_content = True
    display_copyright = hasattr(settings, 'DISPLAY_COPYRIGHT_INFO') and\
        settings.DISPLAY_COPYRIGHT_INFO

    anonymous_can_download_data = False
    if hasattr(settings, 'TSDATA_AVAILABLE_FOR_ANONYMOUS_USERS') and\
            settings.TSDATA_AVAILABLE_FOR_ANONYMOUS_USERS:
        anonymous_can_download_data = True
    tseries = get_object_or_404(Timeseries, id=object_id)
    related_station = tseries.related_station
    kwargs["extra_context"] = {'related_station': related_station,
                              'enabled_user_content':enabled_user_content,
                              'display_copyright': display_copyright,
                              'anonymous_can_download_data':
                                    anonymous_can_download_data}
    kwargs["template_name"] = "timeseries_detail.html"
    return list_detail.object_detail(request, queryset, object_id, *args, **kwargs)


def instrument_detail(request, queryset, object_id, *args, **kwargs):
    """Return the details for a specific timeseries object."""

    enabled_user_content = False
    if hasattr(settings, 'USERS_CAN_ADD_CONTENT'):
        if settings.USERS_CAN_ADD_CONTENT:
            enabled_user_content = True

    instrument = get_object_or_404(Instrument, id=object_id)
    related_station = instrument.station
    try:
        instrument_timeseries = Timeseries.objects.all().filter(instrument__id=object_id)
    except:
        instrument_timeseries = None
    kwargs["extra_context"] = {'related_station': related_station,
                               'enabled_user_content':enabled_user_content,
                               'timeseries': instrument_timeseries}
    kwargs["template_name"] = "instrument_detail.html"
    return list_detail.object_detail(request, queryset, object_id, *args, **kwargs)

def embedmap_view(request, *args, **kwargs):
    return render_to_response('embedmap.html', 
                              {'use_open_layers': settings.USE_OPEN_LAYERS,},
        context_instance=RequestContext(request))

def map_view(request, *args, **kwargs):
    return render_to_response('map_page.html', 
                              {'use_open_layers': settings.USE_OPEN_LAYERS,},
        context_instance=RequestContext(request))

def get_subdivision(request, division_id):
    """Ajax call to refresh divisions in filter table"""
    response = HttpResponse(content_type='text/plain;charset=utf8',
                            mimetype='application/json')
    try:
        div = PoliticalDivision.objects.get(pk=division_id)
    except:
        response.write("[]")
        return response
    parent_divs = PoliticalDivision.objects.filter(Q(name=div.name)&
                                                 Q(name_alt=div.name_alt)&
                                                 Q(short_name=div.short_name)&
                                           Q(short_name_alt=div.short_name_alt))
    divisions = PoliticalDivision.objects.filter(parent__in=[p.id for p in parent_divs])
    response.write("[")
    added = []
    for num,div in enumerate(divisions):
        if not div.name in added:
            response.write(simplejson.dumps({"name": div.name,"id": div.pk}))
            added.append(div.name)
            if num < divisions.count()-1:
                response.write(',')
    response.write("]")
    return response


GF_ERROR = ("The file you requested is temporary unavailable. Please try again"
            " later.")

@gentityfile_permission
def download_gentityfile(request, gf_id):
    """
    This function handles requests for gentityfile downloads and serves the
    content to the user.
    """

    if hasattr(settings, "STORE_TSDATA_LOCALLY") and\
      settings.STORE_TSDATA_LOCALLY:
        gfile = get_object_or_404(GentityFile, pk=int(gf_id))
        try:
            filename = gfile.content.file.name
            wrapper  = FileWrapper(open(filename))
        except:
            raise Http404
        download_name = gfile.content.name.split('/')[-1]
        content_type = mimetypes.guess_type(filename)[0]
        response = HttpResponse(content_type=content_type)
        response['Content-Length'] = os.path.getsize(filename)
        response['Content-Disposition'] = "attachment; filename=%s"%download_name

        for chunk in wrapper:
            response.write(chunk)
    else:
        """
        Fetch GentityFile content from remote instance.
        """
        import urllib2, re, base64

        gfile = get_object_or_404(GentityFile, pk=int(gf_id))

        # Read the creds from the settings file
        REMOTE_INSTANCE_CREDENTIALS = getattr(settings,
                'REMOTE_INSTANCE_CREDENTIALS', {})

        # Get the original GentityFile id and the source database
        if gfile.original_id and gfile.original_db:
            gf_id = gfile.original_id
            db_host = gfile.original_db.hostname
        else:
            request.notifications.error("No data was found for "
                    " the requested Gentity file.")
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None) or '/')

        # Next we check the setting files for a uname/pass for this host
        uname, pwd = REMOTE_INSTANCE_CREDENTIALS.get(db_host, (None,None))

        # We craft the url
        url = 'http://'+db_host + '/api/gfdata/' + str(gf_id)
        req = urllib2.Request(url)
        try:
            handle = urllib2.urlopen(req,timeout=10)
        except IOError, e:
            # here we *want* to fail
            pass
        else:
            # If we don't fail then the page isn't protected
            # which means something is not right. Raise hell
            # mail admins + return user notification.
            request.notifications.error(GF_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None) or '/')

        if not hasattr(e, 'code') or e.code != 401:
            # we got an error - but not a 401 error
            request.notifications.error(GF_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None) or '/')

        authline = e.headers['www-authenticate']
        # this gets the www-authenticate line from the headers
        # which has the authentication scheme and realm in it

        authobj = re.compile(
            r'''(?:\s*www-authenticate\s*:)?\s*(\w*)\s+realm=['"]([^'"]+)['"]''',
            re.IGNORECASE)
        # this regular expression is used to extract scheme and realm
        matchobj = authobj.match(authline)

        if not matchobj:
            # if the authline isn't matched by the regular expression
            # then something is wrong
            request.notifications.error(GF_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None) or '/')

        scheme = matchobj.group(1)
        realm = matchobj.group(2)
        # here we've extracted the scheme
        # and the realm from the header
        if scheme.lower() != 'basic':
            # we don't support other auth
            # mail admins + inform user of error
            request.notifications.error(GF_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None) or '/')

        # now the good part.
        base64string = base64.encodestring(
                '%s:%s' % (uname, pwd))[:-1]
        authheader =  "Basic %s" % base64string
        req.add_header("Authorization", authheader)

        try:
            handle = urllib2.urlopen(req)
        except IOError, e:
            # here we shouldn't fail if the username/password is right
            request.notifications.error(GF_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None) or '/')


        filedata = handle.read()

        download_name = gfile.content.name.split('/')[-1]
        content_type = gfile.file_type.mime_type
        response = HttpResponse(mimetype=content_type)
        response['Content-Length'] = len(filedata)
        response['Content-Disposition'] = "attachment; filename=%s"%download_name
        response.write(filedata)


    return response

@gentityfile_permission
def download_gentitygenericdata(request, gg_id):
    """
    This function handles requests for gentitygenericdata downloads and serves the
    content to the user.
    """
    ggenericdata = get_object_or_404(GentityGenericData, pk=int(gg_id))
    try:
        s = ggenericdata.content
        if s.find('\r')<0:
            s = s.replace('\n', '\r\n')
        (afile_handle, afilename) = mkstemp()
        os.write(afile_handle, s)
        afile = open(afilename, 'r')
        wrapper  = FileWrapper(afile)
    except:
        raise Http404
    download_name = 'GenericData-id_%s.%s'%(gg_id, ggenericdata.data_type.file_extension) 
    content_type = 'text/plain' 
    response = HttpResponse(content_type=content_type)
    response['Content-Length'] = os.fstat(afile_handle).st_size
    response['Content-Disposition'] = "attachment; filename=%s"%download_name
    for chunk in wrapper:
        response.write(chunk)
    return response


TS_ERROR = ("There seems to be some problem with our internal infrastuctrure. The"
" admins have been notified of this and will try to resolve the matter as soon as"
" possible.  Please try again later.")

@timeseries_permission
def download_timeseries(request, object_id):
    """
    This function handles timeseries downloading either from the local db or
    from a remote instance.
    """

    timeseries = get_object_or_404(Timeseries, pk=int(object_id))

    # Check whether this instance has local store enabled or else we need to
    # fetch ts data from remote instance
    if hasattr(settings, 'STORE_TSDATA_LOCALLY') and\
        settings.STORE_TSDATA_LOCALLY:

        t = timeseries # nickname, because we use it much in next statement
        ts = TTimeseries(
            id = int(object_id),
            time_step = ReadTimeStep(object_id, t),
            unit = t.unit_of_measurement.symbol,
            title = t.name,
            timezone = '%s (UTC%+03d%02d)' % (t.time_zone.code,
                (abs(t.time_zone.utc_offset) / 60)* (-1 if t.time_zone.utc_offset<0 else 1), 
                abs(t.time_zone.utc_offset % 60),),
            variable = t.variable.descr,
            precision = t.precision,
            comment = '%s\n\n%s' % (t.gentity.name, t.remarks)
            )
        ts.read_from_db(django.db.connection)
        response = HttpResponse(mimetype=
                                'text/vnd.openmeteo.timeseries; charset=utf-8')
        response['Content-Disposition'] = "attachment; filename=%s.hts"%(object_id,)
        ts.write_file(response)
        return response
    else:
        """
        Here we use the piston api to fetch a specific timeseries data from the
        original database from which it was synced. Since this requires http
        authentication, we use the username/password stored in the settings file to
        connect.

        NOTE: The user used for the sync should be a superuser in the remote
        instance.
        """
        import urllib2, re, base64

        # Read the creds from the settings file
        REMOTE_INSTANCE_CREDENTIALS = getattr(settings,
                'REMOTE_INSTANCE_CREDENTIALS', {})

        # Get the original timeseries id and the source database
        if timeseries.original_id and timeseries.original_db:
            ts_id = timeseries.original_id
            db_host = timeseries.original_db.hostname
        else:
            request.notifications.error("No data was found for "
                    " the requested timeseries.")
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None)
                                or reverse('timeseries_detail',args=[timeseries.id]))

        # Next we check the setting files for a uname/pass for this host
        uname, pwd = REMOTE_INSTANCE_CREDENTIALS.get(db_host, (None,None))

        # We craft the url
        url = 'http://'+db_host + '/api/tsdata/' + str(ts_id)
        req = urllib2.Request(url)
        try:
            handle = urllib2.urlopen(req,timeout=10)
        except IOError, e:
            # here we *want* to fail
            pass
        else:
            # If we don't fail then the page isn't protected
            # which means something is not right. Raise hell
            # mail admins + return user notification.
            request.notifications.error(TS_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None)
                                or reverse('timeseries_detail',args=[timeseries.id]))

        if not hasattr(e, 'code') or e.code != 401:
            # we got an error - but not a 401 error
            request.notifications.error(TS_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None)
                                or reverse('timeseries_detail',args=[timeseries.id]))

        authline = e.headers['www-authenticate']
        # this gets the www-authenticate line from the headers
        # which has the authentication scheme and realm in it

        authobj = re.compile(
            r'''(?:\s*www-authenticate\s*:)?\s*(\w*)\s+realm=['"]([^'"]+)['"]''',
            re.IGNORECASE)
        # this regular expression is used to extract scheme and realm
        matchobj = authobj.match(authline)

        if not matchobj:
            # if the authline isn't matched by the regular expression
            # then something is wrong
            request.notifications.error(TS_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None)
                                or reverse('timeseries_detail',args=[timeseries.id]))

        scheme = matchobj.group(1)
        realm = matchobj.group(2)
        # here we've extracted the scheme
        # and the realm from the header
        if scheme.lower() != 'basic':
            # we don't support other auth
            # mail admins + inform user of error
            request.notifications.error(TS_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None)
                                or reverse('timeseries_detail',args=[timeseries.id]))

        # now the good part.
        base64string = base64.encodestring(
                '%s:%s' % (uname, pwd))[:-1]
        authheader =  "Basic %s" % base64string
        req.add_header("Authorization", authheader)

        try:
            handle = urllib2.urlopen(req)
        except IOError, e:
            # here we shouldn't fail if the username/password is right
            request.notifications.error(TS_ERROR)
            return HttpResponseRedirect(request.META.get('HTTP_REFERER', None)
                                or reverse('timeseries_detail',args=[timeseries.id]))

        tsdata = handle.read()

        response = HttpResponse(mimetype='text/vnd.openmeteo.timeseries;charset=iso-8859-7')
        response['Content-Disposition']="attachment;filename=%s.hts"%(object_id,)

        response.write(tsdata)
        return response

def terms(request):
    return render_to_response('terms.html', RequestContext(request,{}) )

"""
Model management views.
"""

def _station_edit_or_create(request,station_id=None):
    """
    This function updates existing stations and creates new ones.
    """
    from django.forms.models import inlineformset_factory
    user = request.user
    formsets = {}
    if station_id:
        # User is editing a station
        station = get_object_or_404(Station, id=station_id)
        if not (user.has_row_perm(station, 'edit')\
                                and user.has_perm('hcore.change_station')):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
    else:
        # User is creating a new station
        station = None
        if not user.has_perm('hcore.add_station'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    OverseerFormset = inlineformset_factory(Station, Overseer,
                                            extra=1)
    InstrumentFormset = inlineformset_factory(Station, Instrument,
                                            extra=1)
    TimeseriesFormset = inlineformset_factory(Station, Timeseries,
                                            extra=1)

    if request.method == 'POST':
        if station:
            form = StationForm(request.POST,instance=station)
            formsets["Overseer"]  = OverseerFormset(request.POST,
                                    instance=station, prefix='Overseer')
            formsets["Instrument"]  = InstrumentFormset(request.POST,
                                    instance=station, prefix='Instrument')
            formsets["Timeseries"]  = TimeseriesFormset(request.POST,
                                    instance=station, prefix='Timeseries')
        else:
            form = StationForm(request.POST)
            formsets["Overseer"] = OverseerFormset(request.POST,
                                                      prefix='Overseer')
            formsets["Instrument"]  = InstrumentFormset(request.POST,
                                                      prefix='Instrument')
            formsets["Timeseries"]  = TimeseriesFormset(request.POST,
                                                      prefix='Timeseries')

        forms_validated = 0
        for type in formsets:
            if formsets[type].is_valid():
                forms_validated+=1
        if form.is_valid() and forms_validated == len(formsets):
            station = form.save()
            if hasattr(settings, 'USERS_CAN_ADD_CONTENT')\
                and settings.USERS_CAN_ADD_CONTENT:
                    # Make creating user the station creator
                    if not station_id:
                        station.creator = request.user
                        # Give perms to the creator
                        user.add_row_perm(station, 'edit')
                        user.add_row_perm(station, 'delete')
            station.save()
            #Save maintainers, many2many, then save again to
            #set correctly row permissions
            form.save_m2m()
            station.save()
            for type in formsets:
                formsets[type].save()
            if not station_id:
                station_id = str(station.id)
            return HttpResponseRedirect(reverse('station_detail',
                                kwargs={'object_id':station_id}))
    else:
        if station:
            form = StationForm(instance=station,
                               initial={'abscissa': station.gis_abscissa,
                                        'ordinate': station.gis_ordinate})
            formsets["Overseer"]  = OverseerFormset(instance=station,
                                                         prefix='Overseer')
            formsets["Instrument"]  = InstrumentFormset(instance=station,
                                                         prefix='Instrument')
            formsets["Timeseries"]  = TimeseriesFormset(instance=station,
                                                         prefix='Timeseries')
        else:
            form = StationForm()
            formsets["Overseer"]  = OverseerFormset(prefix='Overseer')
            formsets["Instrument"]  = InstrumentFormset(prefix='Instrument')
            formsets["Timeseries"]  = TimeseriesFormset(prefix='Timeseries')

    return render_to_response('station_edit.html', {'form': form,
                            'formsets':formsets, },
                            context_instance=RequestContext(request))

@login_required
def station_edit(request, station_id):
    """
    Edit station details.

    Permissions for editing stations are handled by row level permissions
    """
    return _station_edit_or_create(request, station_id)


@permission_required('hcore.add_station')
def station_add(request):
    """
    Create a new station.

    Permissions for creating stations are handled by django.contrib.auth.
    """
    return _station_edit_or_create(request)

@login_required
def station_delete(request,station_id):
    """
    Delete existing station.

    Permissions for deleting stations are handled by our custom permissions app
    and django.contrib.auth since a user may be allowed to delete a specific
    station but not all of them (specified with row level permissions) or in
    case he is an admin,manager,etc he must be able to delete all of them
    (handled by django.contrib.auth)
    """
    station = Station.objects.get(id=station_id)
    if request.user.has_row_perm(station,'delete') and\
         request.user.has_perm('hcore.delete_station'):
        station.delete()
        ref = request.META.get('HTTP_REFERER', None)
        if ref and not ref.endswith(reverse('station_detail',args=[station_id])):
            return HttpResponseRedirect(ref)
        return render_to_response('success.html',
            {'msg': 'Station deleted successfully',},
            context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')


"""
Timeseries views
"""

def _timeseries_edit_or_create(request,tseries_id=None):
    station_id = None
    station = None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    instrument_id = None
    instrument = None
    if request.GET.has_key('instrument_id'):
        instrument_id=request.GET['instrument_id']
    if tseries_id:
        # Edit
        tseries = get_object_or_404(Timeseries, id=tseries_id)
    else:
        # Add
        tseries = None
    if tseries:
        station = tseries.related_station
        station_id = station.id
        if tseries.instrument: instrument = tseries.instrument
    if instrument_id and not tseries:
        instrument = get_object_or_404(Instrument, id=instrument_id)
        station_id = instrument.station.id
    if station_id and not tseries:
        station = get_object_or_404(Station, id=station_id)
    if station:
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
    if station and not tseries:
        tseries = Timeseries(gentity=station, instrument=instrument)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if tseries and tseries.id:
            form = TimeseriesDataForm(request.POST,request.FILES,instance=tseries,user=user,
                                      gentity_id=station_id, instrument_id=instrument_id)
        else:
            form = TimeseriesForm(request.POST,request.FILES,user=user, gentity_id=station_id,
                                      instrument_id=instrument_id)
        if form.is_valid():
            tseries = form.save()
            # do stuff
            tseries.save()
            if not tseries_id:
                tseries_id=str(tseries.id)
            return HttpResponseRedirect(reverse('timeseries_detail',
                                        kwargs={'object_id':tseries_id}))
    else:
        if tseries and tseries.id:
            form = TimeseriesDataForm(instance=tseries, user=user,
                                      gentity_id=station_id,
                                      instrument_id=instrument_id)
        else:
            form = TimeseriesForm(instance=tseries, user=user,
                                      gentity_id=station_id,
                                      instrument_id=instrument_id)

    return render_to_response('timeseries_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_timeseries')
def timeseries_add(request):
    """
    Create new timeseries. Timeseries can only be added as part of an existing
    station.
    """
    return _timeseries_edit_or_create(request)

@login_required
def timeseries_edit(request,timeseries_id):
    """
    Edit existing timeseries. Permissions are checked against the relative
    station that the timeseries is part of.
    """
    return _timeseries_edit_or_create(request, tseries_id=timeseries_id)

@login_required
def timeseries_delete(request, timeseries_id):
    """
    Delete existing timeseries. Permissions are checked against the relative
    station that the timeseries is part of.
    """
    tseries = get_object_or_404(Timeseries, id=timeseries_id)
    related_station = tseries.related_station
    if tseries and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_timeseries'):
            ts = TTimeseries(int(timeseries_id))
            ts.delete_from_db(django.db.connection)
            tseries.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref and not ref.endswith(reverse('timeseries_detail',args=[timeseries_id])):
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'Timeseries deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')


"""
GentityFile/GenericData/Event Views
"""

def _gentityfile_edit_or_create(request,gfile_id=None):
    station_id=None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    if gfile_id:
        # Edit
        gfile = get_object_or_404(GentityFile, id=gfile_id)
    else:
        # Add
        gfile = None


    if gfile_id:
        station = gfile.related_station
        station_id = station.id
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    if station_id and not gfile_id:
        # Adding new
        station = get_object_or_404(Station, id=station_id)
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
        gevent = GentityFile(gentity=station)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if gfile:
            form = GentityFileForm(request.POST,request.FILES,instance=gfile,user=user)
        else:
            form = GentityFileForm(request.POST,request.FILES,user=user)
        if form.is_valid():
            gfile = form.save()
            # do stuff
            gfile.save()
            if not gfile_id:
                gfile_id=str(gfile.id)
            return HttpResponseRedirect(reverse('station_detail',
                                 kwargs={'object_id': str(gfile.gentity.id)}))
    else:
        if gfile:
            form = GentityFileForm(instance=gfile,user=user,
                                   gentity_id = station_id)
        else:
            form = GentityFileForm(user=user, gentity_id = station_id)

    return render_to_response('gentityfile_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_gentityfile')
def gentityfile_add(request):
    """
    Create new gentityfile. GentityFile can only be added as part of an existing
    station.
    """
    return _gentityfile_edit_or_create(request)

@login_required
def gentityfile_edit(request,gentityfile_id):
    """
    Edit existing gentityfile. Permissions are checked against the relative
    station that the gentityfile is part of.
    """
    return _gentityfile_edit_or_create(request, gfile_id=gentityfile_id)

@login_required
def gentityfile_delete(request, gentityfile_id):
    """
    Delete existing gentityfile. Permissions are checked against the relative
    station that the gentityfile is part of.
    """
    gfile = get_object_or_404(GentityFile, id=gentityfile_id)
    related_station = gfile.related_station
    if gfile and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_gentityfile'):
            gfile.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref:
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'GentityFile deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')


"""
GentityGenericData View
"""

def _gentitygenericdata_edit_or_create(request,ggenericdata_id=None):
    station_id=None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    if ggenericdata_id:
        # Edit
        ggenericdata = get_object_or_404(GentityGenericData, id=ggenericdata_id)
    else:
        # Add
        ggenericdata = None


    if ggenericdata_id:
        station = ggenericdata.related_station
        station_id = station.id
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    if station_id and not ggenericdata_id:
        # Adding new
        station = get_object_or_404(Station, id=station_id)
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
        gevent = GentityGenericData(gentity=station)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if ggenericdata:
            form = GentityGenericDataForm(request.POST,request.FILES,instance=ggenericdata,user=user)
        else:
            form = GentityGenericDataForm(request.POST,request.FILES,user=user)
        if form.is_valid():
            ggenericdata = form.save()
            # do stuff
            ggenericdata.save()
            if not ggenericdata_id:
                ggenericdata_id=str(ggenericdata.id)
            return HttpResponseRedirect(reverse('station_detail',
                                 kwargs={'object_id': str(ggenericdata.gentity.id)}))
    else:
        if ggenericdata:
            form = GentityGenericDataForm(instance=ggenericdata,user=user,
                                          gentity_id=station_id)
        else:
            form = GentityGenericDataForm(user=user, gentity_id=station_id)

    return render_to_response('gentitygenericdata_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_gentityfile')
def gentitygenericdata_add(request):
    """
    Create new gentitygenericdata. GentityGenericData can only be added as part of an existing
    station.
    """
    return _gentitygenericdata_edit_or_create(request)

@login_required
def gentitygenericdata_edit(request,ggenericdata_id):
    """
    Edit existing gentitygenericdata. Permissions are checked against the relative
    station that the gentitygenericdata is part of.
    """
    return _gentitygenericdata_edit_or_create(request, ggenericdata_id=ggenericdata_id)

@login_required
def gentitygenericdata_delete(request, ggenericdata_id):
    """
    Delete existing gentitygenericdata. Permissions are checked against the relative
    station that the gentitygenericdata is part of.
    """
    ggenericdata = get_object_or_404(GentityGenericData, id=ggenericdata_id)
    related_station = ggenericdata.related_station
    if ggenericdata and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_gentityfile'):
            ggenericdata.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref:
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'GentityGenericData deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')


"""
GentityEvent View
"""

def _gentityevent_edit_or_create(request,gevent_id=None):
    station_id=None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    if gevent_id:
        # Edit
        gevent = get_object_or_404(GentityEvent, id=gevent_id)
    else:
        # Add
        gevent = None

    if gevent_id:
        station = gevent.related_station
        station_id = station.id
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    if station_id and not gevent_id:
        # Adding new
        station = get_object_or_404(Station, id=station_id)
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
        gevent = GentityEvent(gentity=station)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if gevent:
            form = GentityEventForm(request.POST,request.FILES,instance=gevent,user=user)
        else:
            form = GentityEventForm(request.POST,request.FILES,user=user)
        if form.is_valid():
            gevent = form.save()
            # do stuff
            gevent.save()
            if not gevent_id:
                gevent_id=str(gevent.id)

            return HttpResponseRedirect(reverse('station_detail',
                        kwargs={'object_id': str(gevent.gentity.id)}))
    else:
        if gevent:
            form = GentityEventForm(instance=gevent,user=user, 
                                    gentity_id = station_id)
        else:
            form = GentityEventForm(user=user, gentity_id = station_id)

    return render_to_response('gentityevent_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_gentityevent')
def gentityevent_add(request):
    """
    Create new gentityevent. GentityEvent can only be added as part of an existing
    station.
    """
    return _gentityevent_edit_or_create(request)

@login_required
def gentityevent_edit(request,gentityevent_id):
    """
    Edit existing gentityevent. Permissions are checked against the relative
    station that the gentityevent is part of.
    """
    return _gentityevent_edit_or_create(request, gevent_id=gentityevent_id)

@login_required
def gentityevent_delete(request, gentityevent_id):
    """
    Delete existing gentityevent. Permissions are checked against the relative
    station that the gentityevent is part of.
    """
    gevent = get_object_or_404(GentityEvent, id=gentityevent_id)
    related_station = gevent.related_station
    if gevent and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_gentityevent'):
            gevent.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref:
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'GentityEvent deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')


def _gentityaltcode_edit_or_create(request,galtcode_id=None):
    station_id=None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    if galtcode_id:
        # Edit
        galtcode = get_object_or_404(GentityAltCode, id=galtcode_id)
    else:
        # Add
        galtcode = None

    if galtcode_id:
        station = galtcode.related_station
        station_id = station.id
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    if station_id and not galtcode_id:
        # Adding new
        station = get_object_or_404(Station, id=station_id)
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
        gevent = GentityAltCode(gentity=station)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if galtcode:
            form = GentityAltCodeForm(request.POST,request.FILES,instance=galtcode,user=user)
        else:
            form = GentityAltCodeForm(request.POST,request.FILES,user=user)
        if form.is_valid():
            galtcode = form.save()
            # do stuff
            galtcode.save()
            if not galtcode_id:
                galtcode_id=str(galtcode.id)
            return HttpResponseRedirect(reverse('station_detail',
                        kwargs={'object_id': str(galtcode.gentity.id)}))
    else:
        if galtcode:
            form = GentityAltCodeForm(instance=galtcode,user=user,
                                      gentity_id = station_id)
        else:
            form = GentityAltCodeForm(user=user, gentity_id = station_id)

    return render_to_response('gentityaltcode_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_gentityaltcode')
def gentityaltcode_add(request):
    """
    Create new gentityaltcode. GentityAltCode can only be added as part of an existing
    station.
    """
    return _gentityaltcode_edit_or_create(request)

@login_required
def gentityaltcode_edit(request,gentityaltcode_id):
    """
    Edit existing gentityaltcode. Permissions are checked against the relative
    station that the gentityaltcode is part of.
    """
    return _gentityaltcode_edit_or_create(request, galtcode_id=gentityaltcode_id)

@login_required
def gentityaltcode_delete(request, gentityaltcode_id):
    """
    Delete existing gentityaltcode. Permissions are checked against the relative
    station that the gentityaltcode is part of.
    """
    galtcode = get_object_or_404(GentityAltCode, id=gentityaltcode_id)
    related_station = galtcode.related_station
    if galtcode and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_gentityaltcode'):
            galtcode.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref:
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'GentityAltCode deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')

"""
Overseer Views
"""

def _overseer_edit_or_create(request,overseer_id=None,station_id=None):
    station_id=None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    if overseer_id:
        # Edit
        overseer = get_object_or_404(Overseer, id=overseer_id)
    else:
        # Add
        overseer = None


    if overseer_id:
        station = overseer.station
        station_id = station.id
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    if station_id and not overseer_id:
        # Adding new
        station = get_object_or_404(Station, id=station_id)
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
        overseer = Overseer(station=station)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if overseer:
            form = OverseerForm(request.POST,request.FILES,instance=overseer,user=user)
        else:
            form = OverseerForm(request.POST,request.FILES,user=user)
        if form.is_valid():
            overseer = form.save()
            # do stuff
            overseer.save()
            if not overseer_id:
                overseer_id=str(overseer.id)
            return HttpResponseRedirect(reverse('station_detail',
                        kwargs={'object_id':str(overseer.station.id)}))
    else:
        if overseer:
            form = OverseerForm(instance=overseer,user=user, 
                                gentity_id = station_id)
        else:
            form = OverseerForm(user=user, gentity_id = station_id)

    return render_to_response('overseer_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_overseer')
def overseer_add(request):
    """
    Create new overseer. Overseer can only be added as part of an existing
    station.
    """
    return _overseer_edit_or_create(request)

@login_required
def overseer_edit(request,overseer_id):
    """
    Edit existing overseer. Permissions are checked against the relative
    station that the overseer is part of.
    """
    return _overseer_edit_or_create(request, overseer_id=overseer_id)

@login_required
def overseer_delete(request, overseer_id):
    """
    Delete existing overseer. Permissions are checked against the relative
    station that the overseer is part of.
    """
    overseer = get_object_or_404(Overseer, id=overseer_id)
    related_station = overseer.station
    if overseer and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_overseer'):
            overseer.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref:
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'Overseer deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')




"""
Instument views
"""

def _instrument_edit_or_create(request,instrument_id=None):
    station_id=None
    if request.GET.has_key('station_id'):
        station_id=request.GET['station_id']
    if instrument_id:
        # Edit
        instrument = get_object_or_404(Instrument, id=instrument_id)
    else:
        # Add
        instrument = None

    if instrument_id:
        station = instrument.station
        station_id = station.id
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')

    if station_id and not instrument_id:
        station = get_object_or_404(Station, id=station_id)
        if not request.user.has_row_perm(station,'edit'):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
        instrument = Instrument(station=station)

    user = request.user
    # Done with checks
    if request.method == 'POST':
        if instrument:
            form = InstrumentForm(request.POST,instance=instrument,user=user)
        else:
            form = InstrumentForm(request.POST,user=user)
        if form.is_valid():
            instrument = form.save()
            # do stuff
            instrument.save()
            if not instrument_id:
                instrument_id=str(instrument.id)
            return HttpResponseRedirect(reverse('instrument_detail',
                        kwargs={'object_id':instrument_id}))
    else:
        if instrument:
            form = InstrumentForm(instance=instrument,user=user,
                                  gentity_id = station_id)
        else:
            form = InstrumentForm(user=user, gentity_id = station_id)

    return render_to_response('instrument_edit.html', {'form': form},
                    context_instance=RequestContext(request))

@permission_required('hcore.add_instrument')
def instrument_add(request):
    """
    Create new instrument. Timeseries can only be added as part of an existing
    station.
    """
    return _instrument_edit_or_create(request)

@login_required
def instrument_edit(request,instrument_id):
    """
    Edit existing instrument. Permissions are checked against the relative
    station that the instrument is part of.
    """
    return _instrument_edit_or_create(request, instrument_id=instrument_id)

@login_required
def instrument_delete(request, instrument_id):
    """
    Delete existing instrument. Permissions are checked against the relative
    station that the instrument is part of.
    """
    instrument = get_object_or_404(Instrument, id=instrument_id)
    related_station = instrument.station
    if instrument and related_station:
        if request.user.has_row_perm(related_station, 'edit') and\
         request.user.has_perm('hcore.delete_instrument'):
            instrument.delete()
            ref = request.META.get('HTTP_REFERER', None)
            if ref and not ref.endswith(reverse('instrument_detail',args=[instrument_id])):
                return HttpResponseRedirect(ref)
            return render_to_response('success.html',
                    {'msg': 'Instrument deleted successfully',},
                    context_instance=RequestContext(request))
    return HttpResponseForbidden('Forbidden', mimetype='text/plain')




"""
Generic model creation
"""

ALLOWED_TO_EDIT = ('waterbasin', 'waterdivision', 'person', 'organization',
                   'stationtype', 'variable', 'timezone',
                   'politicaldivision','instrumenttype', 'unitofmeasurement',
                   'filetype','eventtype','gentityaltcodetype','timestep',
                   'gentityaltcode', 'gentityfile', 'gentityevent',
                   'gentitygenericdatatype')

@login_required
def model_add(request, model_name=''):
    popup = request.GET.get('_popup', 0) == '1'
    if not popup and request.method == 'GET'\
                                    and not '_complete' in request.GET:
        raise Http404
    try:
       model = ContentType.objects.get(model=model_name,
                                       app_label='hcore').model_class()
    except (ContentType.DoesNotExist, ContentType.MultipleObjectsReturned):
        raise Http404
    if not model_name in ALLOWED_TO_EDIT\
       or not request.user.has_perm('hcore.add_'+model_name):
            return HttpResponseForbidden('Forbidden', mimetype='text/plain')
    if '_complete' in request.GET:
        if request.GET['_complete'] == '1':
            newObject = model.objects.order_by('-pk')[0]
            return HttpResponse('<script type="text/javascript"'
                 'src="%(s)admin/js/admin/RelatedObjectLookups.js"></script>'
                 '<script type="text/javascript">'
                 'opener.dismissAddAnotherPopup(window,"%s","%s");</script>'\
                 % (settings.STATIC_URL, escape(newObject._get_pk_val()),
                 escape(newObject)))
    return create_object(request, model,
                post_save_redirect=reverse('model_add',
                    kwargs={'model_name':lower(model.__name__)})+"?_complete=1",
                template_name='model_add.html',
                form_class= TimeStepForm if model.__name__=='TimeStep' else None,
                extra_context={'form_prefix': model.__name__,})

# Profile page
def profile_view(request, username):
    from profiles.views import profile_detail
    if request.user and request.user.username == username:
        extra_content = {'user_enabled_content': getattr(settings,
                                   'USERS_CAN_ADD_CONTENT', False)}
        return profile_detail(request, username, extra_context=extra_content)
    else:
        user = get_object_or_404(User, username=username)
        return render_to_response('profiles/profile_public.html',
            { 'profile': user.get_profile()} ,
            context_instance=RequestContext(request))

def clean_kml_request(tuppleitems):
    try:
        items = {}
        for item in tuppleitems:
            items[item[0].lower()] = item[1] 
        klist = ('service', 'version', 'request', 'srs', 'bbox')
        for key in klist:
            if items.has_key(key):
                items.pop(key)
        return items
    except Exception, e:
        raise Http404

def kml(request, layer):
    try:
        bbox=request.GET.get('BBOX', request.GET.get('bbox', None))
        agentity_id = request.GET.get('gentity_id', request.GET.get('GENTITY_ID', None));
    except Exception, e:
        raise Http404
    if bbox:
        try:
            minx, miny, maxx, maxy=[float(i) for i in bbox.split(',')]
            geom=Polygon(((minx,miny),(minx,maxy),(maxx,maxy),(maxx,miny),(minx,miny)),srid=4326)
        except Exception, e:
            raise Http404
    try:
        getparams = clean_kml_request(request.GET.items())
        station_objects = Station.objects.all()
        if len(settings.SITE_STATION_FILTER)>0:
            station_objects = station_objects.filter(**settings.SITE_STATION_FILTER)
        queryres = station_objects.filter(point__isnull=False)
        if getparams.has_key('check') and getparams['check']=='search':
            query_string = request.GET.get('q', request.GET.get('Q', ""))
            search_terms = query_string.split()
            if search_terms:
                queryres = queryres.filter(get_search_query(search_terms)).distinct()
        else:
            if agentity_id:
                queryres = queryres.filter(id=agentity_id)
            if bbox:
                queryres = queryres.filter(point__contained=geom)
            if getparams.has_key('owner'):
                queryres = queryres.filter(owner__id=getparams['owner'])
            if getparams.has_key('type'):
                queryres = queryres.filter(type__id=getparams['type'])
            if getparams.has_key('political_division'):
                leaves = PoliticalDivision.objects.get_leaf_subdivisions(\
                                  PoliticalDivision.objects.filter(id=getparams['political_division']))
                queryres = queryres.filter(political_division__in=leaves)
            if getparams.has_key('water_basin'):
                queryres = queryres.filter(Q(water_basin__id=getparams['water_basin']) | \
                                           Q(water_basin__parent=getparams['water_basin']))
            if getparams.has_key('water_division'):
                queryres = queryres.filter(water_division__id=getparams['water_division'])
            if getparams.has_key('variable'):
                queryres = queryres.filter(id__in=\
                      Timeseries.objects.all().filter(variable__id=getparams['variable']).values_list('gentity', flat=True)).distinct()
        if getparams.has_key('ts_only'):
            tmpset = queryres.annotate(tsnum=Count('timeseries'))
            queryres = tmpset.exclude(tsnum=0)
    except Exception, e:
        raise Http404
    for arow in queryres:
        if arow.point: 
            arow.kml = arow.point.kml
    response = render_to_kml("placemarks.kml", {'places': queryres})
    return response

def bound(request):
    agentity_id = request.GET.get('gentity_id', request.GET.get('GENTITY_ID', None));
    getparams = clean_kml_request(request.GET.items())
    station_objects = Station.objects.all()
    if len(settings.SITE_STATION_FILTER)>0:
        station_objects = station_objects.filter(**settings.SITE_STATION_FILTER)
    queryres = station_objects
    if getparams.has_key('check') and getparams['check']=='search':
        query_string = request.GET.get('q', request.GET.get('Q', ""))
        search_terms = query_string.split()
        if search_terms:
            queryres = queryres.filter(get_search_query(search_terms))
    elif getparams.has_key('bounded'):
        bound_str = getparams['bounded'].replace('%2C',',').replace('%2c',',')
        minx, miny, maxx, maxy=[float(i) for i in bound_str.split(',')]
        dx = (maxx-minx)/2000
        dy = (maxy-miny)/2000
        minx+=dx
        miny-=dx
        miny+=dy
        maxy-=dy
        return HttpResponse("%f,%f,%f,%f"%(minx,miny,maxx,maxy), mimetype='text/plain') 
    else:
        if agentity_id:
            queryres = queryres.filter(id=agentity_id)
        if getparams.has_key('owner'):
            queryres = queryres.filter(owner__id=getparams['owner'])
        if getparams.has_key('type'):
            queryres = queryres.filter(type__id=getparams['type'])
        if getparams.has_key('political_division'):
            leaves = PoliticalDivision.objects.get_leaf_subdivisions(\
                              PoliticalDivision.objects.filter(id=getparams['political_division']))
            queryres = queryres.filter(political_division__in=leaves)
        if getparams.has_key('water_basin'):
            queryres = queryres.filter(Q(water_basin__id=getparams['water_basin']) | \
                                       Q(water_basin__parent=getparams['water_basin']))
        if getparams.has_key('water_division'):
            queryres = queryres.filter(water_division__id=getparams['water_division'])
        if getparams.has_key('variable'):
            queryres = queryres.filter(id__in=\
                  Timeseries.objects.all().filter(variable__id=getparams['variable']).values_list('gentity', flat=True))
    if getparams.has_key('ts_only'):
        tmpset = queryres.annotate(tsnum=Count('timeseries'))
        queryres = tmpset.exclude(tsnum=0)
    if queryres.count()<1:
        return HttpResponse(','.join([str(e) for e in\
                            settings.MAP_DEFAULT_VIEWPORT]), mimetype='text/plain')
    try:
        extent = list(queryres.extent())
    except TypeError:
        return HttpResponse(','.join([str(e) for e in\
                            settings.MAP_DEFAULT_VIEWPORT]), mimetype='text/plain')
    min_viewport = settings.MIN_VIEWPORT_IN_DEGS
    min_viewport_half = 0.5*min_viewport
    if abs(extent[2]-extent[0])<min_viewport:
        extent[2]+=min_viewport_half
        extent[0]-=min_viewport_half
    if abs(extent[3]-extent[1])<min_viewport:
        extent[3]+=min_viewport_half
        extent[1]-=min_viewport_half
    return HttpResponse(','.join([str(e) for e in extent]), mimetype='text/plain')
