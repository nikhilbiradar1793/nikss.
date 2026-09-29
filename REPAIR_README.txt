NIKSS CODING HUB — FIXED COMPLETE REPAIR PACK
===============================================

This pack fixes the errors visible in the supplied Flask logs and the navbar-only page problem.

ROOT CAUSES FOUND
-----------------
1. The running Flask app was NOT the same project you uploaded.
   The logs show: C:\new project 938\app.py
   Your project should be run from the NIKSS Coding Hub project directory.

2. chatbot.html was missing from the active templates directory.
   Flask raised: jinja2.exceptions.TemplateNotFound: chatbot.html

3. admin_dashboard.html was missing from the active templates directory.
   Flask raised: jinja2.exceptions.TemplateNotFound: admin_dashboard.html

4. The browser requested course images that did not exist:
   /static/uploads/python.jpg
   /static/uploads/cybersecurity.jpg
   /static/uploads/web-development.jpg
   /static/uploads/data-analytics.jpg
   /static/uploads/networking.jpg
   /static/uploads/flask.jpg
   Placeholder images are included in this pack.

5. The supplied redesigned chatbot JavaScript sent form-urlencoded data, while the Flask
   chatbot_message route reads request.get_json(). The chatbot is corrected to send JSON.

6. The CSS/page shell is hardened against a parent height/overflow rule causing the page to
   render like a thin navbar strip. The active stylesheet name is nikss-premium.css, matching
   the stylesheet requested by your current logs.

7. The supplied backend contains /student/dashboard and /admin + /admin/dashboard routes.
   The 404 seen for /student/dashboard therefore indicates that the server was running a
   different/older app.py. This pack includes the supplied current app.py.

WHAT TO COPY
------------
Copy these into the SAME folder that contains the app.py you actually run:

- app.py
- requirements.txt
- templates/*
- static/css/nikss-premium.css
- static/css/nikss.css
- static/js/nikss.js
- static/uploads/* (placeholder course images)

DO NOT overwrite your database or .env.
Keep your existing nikss_coding_hub.db and .env.

WINDOWS RUN STEPS
-----------------
Open PowerShell in your NIKSS project folder, for example:

  cd C:\NIKSS_CODING_HUB

Confirm you are in the correct folder:

  Get-Location
  dir app.py
  dir templates

Install dependencies:

  py -m pip install -r requirements.txt

Run the app:

  py app.py

Then open:

  http://127.0.0.1:5000/

IMPORTANT
---------
Do not run an old copy from C:\new project 938.
If the terminal says the traceback comes from another folder, stop that process and start
this project's app.py.

GOOGLE LOGIN
------------
The login template uses the existing endpoint:
  /login/google

The supplied backend defines google_login and google_callback. Keep your Google OAuth
credentials in .env/environment variables; never put them in GitHub.

CHATBOT
-------
The page is /chatbot and the message endpoint is the same /chatbot route with POST.
The frontend now sends JSON, matching request.get_json() in app.py.

VIDEO LEARNING
--------------
The backend routes include:
  /student/dashboard
  /learn/<course_id>
  /student/course/<course_id>/learn
  /uploads/videos/<path:filename>
  /course/<course_id>/video/<video_id>/complete

Do not delete your uploaded video files.


ADMIN GOOGLE CONFIGURATION
--------------------------
The following Google accounts are pre-configured as administrators:
- nikhilbiradar53@gmail.com
- nikhilbiradar1793@gmail.com
- nikhilbiradar9405@gmail.com

Admin login flow:
1. Open the NIKSS login page.
2. Click Continue with Google.
3. Sign in with one of the three configured Google accounts.
4. Google must report the email as verified.
5. The application assigns role=admin and redirects to /admin/dashboard.

Other Google accounts follow the student registration/verification flow and do not get
Admin Dashboard access. The application no longer prints the admin email addresses as
login details when it starts.
