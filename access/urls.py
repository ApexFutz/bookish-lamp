from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("me/", views.dashboard, name="dashboard"),
    path("matrix/", views.matrix, name="matrix"),
    # path("employees/", views.employee_directory, name="employee_directory"),  # TODO: implement
    # path("equipment/", views.equipment_directory, name="equipment_directory"),  # TODO: implement
    # path("equipment/add/", views.add_equipment, name="add_equipment"),  # TODO: implement
    # path("equipment/remove/", views.remove_equipment, name="remove_equipment"),  # TODO: implement
    # path("training/", views.training_queue, name="training_queue"),  # TODO: implement
    # path("training/add/", views.add_training_requirement, name="add_training_requirement"),  # TODO: implement
    # path("training/complete/", views.complete_training, name="complete_training"),  # TODO: implement
    # path("roster/", views.roster, name="roster"),  # TODO: implement
    # path("roster/create/", views.create_employee, name="create_employee"),  # TODO: implement
    # path("roster/delete/", views.delete_employee, name="delete_employee"),  # TODO: implement
    # path("roster/recertify/", views.update_recertification, name="update_recertification"),  # TODO: implement
    # path("grant/", views.grant_qualification, name="grant_qualification"),  # TODO: implement
]
