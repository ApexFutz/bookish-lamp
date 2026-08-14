from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("me/", views.dashboard, name="dashboard"),
    path("matrix/", views.matrix, name="matrix"),
    path("employees/", views.employee_directory, name="employee_directory"),
    path("equipment/", views.equipment_directory, name="equipment_directory"),
    path("equipment/add/", views.add_equipment, name="add_equipment"),
    path("equipment/remove/", views.remove_equipment, name="remove_equipment"),
    path("training/", views.training_queue, name="training_queue"),
    path("training/add/", views.add_training_requirement, name="add_training_requirement"),
    path("training/complete/", views.complete_training, name="complete_training"),
    path("roster/", views.roster, name="roster"),
    path("roster/create/", views.create_employee, name="create_employee"),
    path("roster/delete/", views.delete_employee, name="delete_employee"),
    path("roster/recertify/", views.update_recertification, name="update_recertification"),
    path("grant/", views.grant_qualification, name="grant_qualification"),
]
