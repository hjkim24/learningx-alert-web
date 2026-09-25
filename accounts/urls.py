from django.urls import path

from . import views


urlpatterns = [
    path("canvas/", views.canvas_connect, name="canvas_connect"),
    path("canvas/disconnect/", views.canvas_disconnect, name="canvas_disconnect"),
    path("courses/", views.course_settings, name="course_settings"),
    path("courses/save/", views.course_settings_save, name="course_settings_save"),
    path("preview/", views.preview, name="preview"),
    path("destination/save/", views.destination_save, name="destination_save"),
    path("destination/delete/", views.destination_delete, name="destination_delete"),
    path("destination/test/", views.destination_test, name="destination_test"),
]
