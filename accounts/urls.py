from django.urls import path

from . import views


urlpatterns = [
    path("canvas/", views.canvas_connect, name="canvas_connect"),
    path("canvas/disconnect/", views.canvas_disconnect, name="canvas_disconnect"),
    path("courses/", views.course_settings, name="course_settings"),
    path("courses/save/", views.course_settings_save, name="course_settings_save"),
]
