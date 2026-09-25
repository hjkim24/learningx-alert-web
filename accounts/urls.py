from django.urls import path

from . import views


urlpatterns = [
    path("canvas/", views.canvas_connect, name="canvas_connect"),
    path("canvas/disconnect/", views.canvas_disconnect, name="canvas_disconnect"),
]
