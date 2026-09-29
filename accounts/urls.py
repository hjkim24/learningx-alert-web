from django.urls import path

from . import views


urlpatterns = [
    path("canvas/", views.canvas_connect, name="canvas_connect"),
    path("canvas/disconnect/", views.canvas_disconnect, name="canvas_disconnect"),
    path("courses/", views.course_settings, name="course_settings"),
    path("courses/sync/", views.course_sync, name="course_sync"),
    path("courses/save/", views.course_settings_save, name="course_settings_save"),
    path("preview/", views.preview, name="preview"),
    path("excluded/", views.excluded_items, name="excluded_items"),
    path("excluded/add/", views.item_exclude, name="item_exclude"),
    path("excluded/<int:pk>/remove/", views.item_include, name="item_include"),
    path("notifications/", views.notification_settings, name="notification_settings"),
    path(
        "notifications/destinations/",
        views.destination_settings,
        name="destination_settings",
    ),
    path("account/", views.account_settings, name="account_settings"),
    path(
        "notifications/save/",
        views.notification_settings_save,
        name="notification_settings_save",
    ),
    path(
        "notifications/rule/",
        views.notification_rule_save,
        name="notification_rule_save",
    ),
    path("destination/save/", views.destination_save, name="destination_save"),
    path(
        "destination/<int:pk>/delete/",
        views.destination_delete,
        name="destination_delete",
    ),
    path(
        "destination/<int:pk>/test/",
        views.destination_test,
        name="destination_test",
    ),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("push/unsubscribe/", views.push_unsubscribe, name="push_unsubscribe"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("account/delete/", views.account_delete, name="account_delete"),
]
