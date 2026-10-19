from django.urls import path

from . import views

app_name = "training"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("manage/", views.manage_catalog, name="manage"),
    path("manage/courses/<int:course_id>/", views.edit_course, name="edit_course"),
    path("manage/cohorts/<int:cohort_id>/", views.edit_cohort, name="edit_cohort"),
    path("cohorts/<int:cohort_id>/status/", views.change_cohort_status, name="change_status"),
    path("enroll/", views.enroll, name="enroll"),
    path("cohorts/<int:cohort_id>/", views.cohort_detail, name="cohort"),
    path("cohorts/<int:cohort_id>/sessions/", views.create_session, name="create_session"),
    path("sessions/<int:session_id>/attendance/<int:enrollment_id>/", views.mark_attendance, name="attendance"),
    path("cohorts/<int:cohort_id>/assessments/", views.create_assessment, name="create_assessment"),
    path("assessments/<int:assessment_id>/results/<int:enrollment_id>/", views.grade_assessment, name="grade_assessment"),
    path("enrollments/<int:enrollment_id>/certificate/", views.issue_student_certificate, name="issue_certificate"),
    path("certificates/<int:certificate_id>/", views.certificate_detail, name="certificate"),
    path("certificates/<int:certificate_id>/revoke/", views.revoke_student_certificate, name="revoke_certificate"),
]
