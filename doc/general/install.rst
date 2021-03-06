.. _install:

==============================
Installation and configuration
==============================

.. highlight:: bash

Prerequisites
=============

===================================================== ============
Prerequisite                                          Version
===================================================== ============
Python with setuptools and pip                        2.7 [1]
PostgreSQL                                            [2]
PostGIS                                               [3]
GDAL                                                  1.9
psycopg2                                              2.2 [4]
PIL or Pillow with freetype                           1.1.7 [5]
Dickinson                                             0.1.0 [6]
===================================================== ============

.. admonition:: Note for production installations

   These prerequisites are for development installations. For
   production installations you also need a web server.

[1] Enhydris runs on Python 2.6 and 2.7. It should also run on
any later 2.x version. Enhydris does not run on Python 3.  setuptools
and pip are needed in order to install the rest of the Python modules.

[2] Enhydris should run on all supported PostgreSQL versions.  In
order to avoid possible incompatibilities with psycopg2, it is better
to use the version prepackaged by your operating system when running
on GNU/Linux, and to use the latest PostgreSQL version when running on
Windows.

[3] Except for PostGIS, more libraries, namely geos and proj, are
needed; however, you probably not need to worry about that, because in
most GNU/Linux distributions PostGIS has a dependency on them and
therefore they will be installed automatically, whereas in Windows the
installation file of PostGIS includes them. Enhydris is known to run
on PostGIS 2.1. It probably can run on most previous and later
versions as well.

[4] psycopg2 is an Enhydris dependency, and when you install Enhydris,
:command:`pip` will attempt to install psycopg2. However, it can be
tricky to install (because it needs compilation and has a dependency
on PostgreSQL client libraries, which probably means you must have
PostgreSQL's development files installed), and it is therefore usually
better to install a prepackaged version for your operating system.

[5] PIL/Pillow is not directly required by Enhydris, but by other
python modules required my Enhydris. In theory, installing Enhydris
with :command:`pip` will indirectly result in also installing
PIL/Pillow.  However, it can be tricky to install, and it may be
better to install a prepackaged version for your operating
system. It must be compiled with libfreetype support. This is common
in Linux distributions.

[6] Dickinson_ is not required directly by Enhydris, but by pthelma_,
which is required by Enhydris.

.. _dickinson: http://dickinson.readthedocs.org/
.. _pthelma: http://pthelma.readthedocs.org/

.. admonition:: Example: Installing prerequisites on Debian/Ubuntu

   These instructions are for Debian jessie. For Ubuntu they are similar,
   except that the postgis package version may be different::

      apt-get install python postgresql postgis postgresql-9.4-postgis \
          python-psycopg2 python-setuptools python-pip python-pil \
          python-gdal

      # Install Dickinson
      cd /tmp
      wget https://github.com/openmeteo/dickinson/archive/0.2.0.tar.gz
      tar xzf 0.2.0.tar.gz
      cd dickinson-0.2.0
      ./configure
      make
      sudo make install


Creating a spatially enabled database
=====================================

You need to create a database user and a spatially enabled database
(we use ``enhydris_user`` and ``enhydris_db`` in the examples below).
Enhydris will be connecting to the database as that user. The user
should not be a super user, not be allowed to create databases, and
not be allowed to create more users.

.. admonition:: GNU example

   First, you need to create a spatially enabled database template. For
   PostGIS 2.0 or later::

      sudo -u postgres -s
      createdb template_postgis
      psql -d template_postgis -c "CREATE EXTENSION postgis;"
      psql -d template_postgis -c \
         "UPDATE pg_database SET datistemplate='true' \
         WHERE datname='template_postgis';"
      exit

   The create the database::

      sudo -u postgres -s
      createuser --pwprompt enhydris_user
      createdb --template template_postgis --owner enhydris_user \
         enhydris_db
      exit

   You may also need to edit your ``pg_hba.conf`` file as needed
   (under ``/var/lib/pgsql/data/`` or ``/etc/postgresql/8.x/main/``,
   depending on your system). The chapter on `client authentication`_
   of the PostgreSQL manual explains this in detail. A simple setup is
   to authenticate with username and password, in which case you
   should add or modify the following lines in ``pg_hba.conf``::

       local   all         all                               md5
       host    all         all         127.0.0.1/32          md5
       host    all         all         ::1/128               md5

   Restart the server to read the new ``pg_hba.conf`` configuration.
   For example::

       service postgresql restart

   .. _client authentication: http://www.postgresql.org/docs/9.4/static/client-authentication.html

.. admonition:: Windows example

   Assuming PostgreSQL is installed at the default location, run these
   at a command prompt::
   
      cd C:\Program Files\PostgreSQL\9.4\bin
      createdb template_postgis
      psql -d template_postgis -c "CREATE EXTENSION postgis;"
      psql -d template_postgis -c "UPDATE pg_database SET datistemplate='true'
         WHERE datname='template_postgis';"
      createuser -U postgres --pwprompt enhydris_user
      createdb --template template_postgis --owner enhydris_user enhydris_db

   At some point, these commands will ask you for the password of the
   operating system user.

Install Enhydris
================

Install Enhydris with :command:`pip install enhydris`, probably
specifying a version and using a virtualenv, like this::

    virtualenv --system-site-packages [virtualenv_target_dir]
    pip install 'enhydris>=0.5,<0.6'

You may or may not want to use the ``--system-site-packages``
parameter. The main reason to use it is that it will then use your
systemwide ``python-gdal``, ``python-psycopg2``, and ``python-pil``,
which means it won't need to compile these for the virtualenv.

Configuring Enhydris
====================

Execute :command:`enhydris-admin newinstance` to create a new Enhydris
configuration directory; for example::

    cd /etc
    enhydris-admin newinstance myinstance

The above will create directory :file:`/etc/myinstance` with some
files in it.

Open the created file :file:`settings.py` and edit it according to the
comments you will find in the file.

Initializing the database
=========================

In order to initialize your database and create the necessary database
tables for Enhydris to run, run the following commands inside the
Enhydris configuration directory::

   python manage.py migrate
   python manage.py createsuperuser

The above commands will also ask you to create a Enhydris superuser.

.. admonition:: Confused by users?

   There are operating system users, database users, and Enhydris
   users. PostgreSQL runs as an operating system user, and so does the
   web server, and so does Django and therefore Enhydris. Now the
   application (i.e. Enhydris/Django) needs a database connection to
   work, and for this connection it connects to the database as a
   database user.  For the end users, that is, for the actual people
   who use Enhydris, Enhydris/Django keeps a list of usernames and
   passwords in the database, which have nothing to do with operating
   system users or database users. The Enhydris superuser created by
   the ``python manage.py createsuperuser`` command is such an Enhydris
   user, and is intended to represent a human.


Running Enhydris
================

Inside the Enhydris configuration directory, run the following
command::

    python manage.py runserver

The above command will start the Django development server and set it
to listen to port 8000. If you then start your browser and point it to
``http://localhost:8000/``, you should see Enhydris in action. Note
that this only listens to the localhost; if you want it to listen on
all interfaces, use ``0.0.0.0:8000`` instead.

To use Enhydris in production, you need to setup a web server such as
apache. This is described in detail in `Deploying Django`_.

.. _deploying django: http://docs.djangoproject.com/en/1.8/howto/deployment/


Post-install configuration: domain name
=======================================

After you run Enhydris, logon as a superuser, visit the admin panel,
go to ``Sites``, edit the default site, and enter your domain name
there instead of ``example.com``. Emails to users for registration
confirmation will contain links to that domain.  Restart the
Enhydris (by restarting apache/gunicorn/whatever) after changing the
domain name.


.. _settings:

Settings reference
==================
 
These are the settings available to Enhydris, in addition to the
`Django settings`_.

.. _django settings: http://docs.djangoproject.com/en/1.8/ref/settings/

.. data:: ENHYDRIS_FILTER_DEFAULT_COUNTRY

   When a default country is specified, the station search is locked
   within that country and the station search filter allows only searches
   in the selected country. If left blank, the filter allows all
   countries to be included in the search.

.. data:: ENHYDRIS_FILTER_POLITICAL_SUBDIVISION1_NAME
.. data:: ENHYDRIS_FILTER_POLITICAL_SUBDIVISION2_NAME 

   These are used only if :data:`FILTER_DEFAULT_COUNTRY` is set. They
   are the names of the first and the second level of political
   subdivision in a certain country.  For example, Greece is first
   divided in 'districts', then in 'prefecture', whereas the USA is
   first divided in 'states', then in 'counties'.

.. data:: ENHYDRIS_USERS_CAN_ADD_CONTENT

   This must be configured before syncing the database. If set to
   ``True``, it enables all logged in users to add content to the site
   (stations, instruments and timeseries). It enables the use of user
   space forms which are available to all registered users and also
   allows editing existing data. When set to ``False`` (the default),
   only privileged users are allowed to add/edit/remove data from the
   db.

.. data:: ENHYDRIS_SITE_CONTENT_IS_FREE

   If this is set to ``True``, all registered users have access to the
   timeseries and can download timeseries data. If set to ``False``
   (the default), the users may be restricted.


.. data:: ENHYDRIS_TSDATA_AVAILABLE_FOR_ANONYMOUS_USERS

   Setting this option to ``True`` will enable all users to download
   timeseries data without having to login first. The default is
   ``False``.

.. data:: ENHYDRIS_MIN_VIEWPORT_IN_DEGS

   Set a value in degrees. When a geographical query has a bounding
   box with dimensions less than :data:`MIN_VIEWPORT_IN_DEGS`, the map
   will have at least a dimension of ``MIN_VIEWPORT_IN_DEGS²``. Useful
   when showing a single entity, such as a hydrometeorological
   station. Default value is 0.04, corresponding to an area
   approximately 4×4 km.

.. data:: ENHYDRIS_MAP_DEFAULT_VIEWPORT

   A tuple containing the default viewport for the map in geographical
   coordinates, in cases of geographical queries that do not return
   anything.  Format is (minlon, minlat, maxlon, maxlat) where lon and
   lat is in decimal degrees, positive for north/east, negative for
   west/south.

.. data:: ENHYDRIS_TS_GRAPH_CACHE_DIR

   The directory in which timeseries graphs are cached. It is
   automatically created if it does not exist. The default is
   subdirectory :file:`enhydris-timeseries-graphs` of the system or
   user temporary directory.

.. data:: ENHYDRIS_TS_GRAPH_BIG_STEP_DENOMINATOR
          ENHYDRIS_TS_GRAPH_FINE_STEP_DENOMINATOR

   Chart options for time series details page. The big step represents
   the max num of data points to be plotted, default is 200. The fine
   step are the max num of points between main data points to search
   for a maxima, default is 50. 

.. data:: ENHYDRIS_SITE_STATION_FILTER

   This is a quick-and-dirty way to create a web site that only
   displays a subset of an Enhydris database. For example, the
   database of http://system.deucalionproject.gr/ is the same as that
   of http://openmeteo.org/; however, the former only shows stations
   relevant to the Deucalion project, because it has this setting::

      ENHYDRIS_SITE_STATION_FILTER = {'owner__id__exact': '9'}

.. data:: ENHYDRIS_DISPLAY_COPYRIGHT_INFO

   If ``True``, the station detail page shows copyright information
   for the station. By default, it is ``False``. If all the stations
   in the database belong to one organization, you probably want to
   leave it to ``False``. If the database is going to be openly
   accessed and contains data that belongs to many owners, you
   probably want to set it to ``True``.

.. data:: ENHYDRIS_WGS84_NAME

   Sometimes Enhydris displays the reference system of the
   co-ordinates, which is always WGS84. In some installations, it is
   desirable to show something other than "WGS84", such as "ETRS89".
   This parameter specifies the name that will be displayed; the
   default is WGS84.

   This is merely a cosmetic issue, which does not affect the actual
   reference system used, which is always WGS84. The purpose of this
   parameter is merely to enable installations in Europe to display
   "ETRS89" instead of "WGS84" whenever this is preferred. Given that
   the difference between WGS84 and ETRS89 is only a few centimeters,
   which is considerably less that the accuracy with which
   station co-ordinates are given, whether WGS84 or ETRS89 is
   displayed is actually irrelevant.

.. data:: ENHYDRIS_MAP_BASE_LAYERS

   A list of Javascript definitions of base layers to use on the map.
   The default is::

        [r'''OpenLayers.Layer.OSM.Mapnik("Open Street Map",
            {isBaseLayer: true,
            attribution: "Map by <a href='http://www.openstreetmap.org/'>OSM</a>"})''',
         r'''OpenLayers.Layer.OSM.CycleMap("Open Cycle Map",
            {isBaseLayer: true,
                attribution: "Map by <a href='http://www.openstreetmap.org/'>OSM</a>"})'''
        ]

.. data:: ENHYDRIS_MAP_BOUNDS

   A pair of points, each one being a pair of co-ordinates in WGS84; the first
   one is the bottom-left point and the second is the top-right. The default
   is Greece::

       ENHYDRIS_MAP_BOUNDS = ((19.3, 34.75), (29.65, 41.8))

   The bounds are automatically enlarged in order to encompass all registered
   objects, so this setting is useful only if there are no objects or a few
   objects.

.. data:: ENHYDRIS_MAP_MARKERS

   The map can show different station types with different markers. For
   example::

      ENHYDRIS_MAP_MARKERS = {
          '0': 'images/drop_marker.png',
          '1': 'images/drop_marker_cyan.png',
          '3': 'images/drop_marker_orange.png',
          '11': 'images/drop_marker_green.png',
      }
                                
   In the example above, stations whose type id is 3 will be shown with
   :file:`drop_marker_orange.png`, and any marker whose id is not one
   of 1, 3, or 11 will show with :file:`drop_marker.png`. The files
   are URLs; if they are relative, they are relative to
   :data:`STATIC_URL`.

   The default is::

      ENHYDRIS_MAP_MARKERS = {
          '0': 'images/drop_marker.png', 
      }
