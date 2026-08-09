from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("matrix/", views.matrix, name="matrix"),
    path("grant/", views.grant_qualification, name="grant_qualification"),
]
