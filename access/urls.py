from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("me/", views.dashboard, name="dashboard"),
    path("matrix/", views.matrix, name="matrix"),
    # Employees (specific routes before the <shift> catch-all)
    path("employees/", views.employees_index, name="employees_index"),
    path("employees/add/", views.employee_add, name="employee_add"),
    path("employees/remove/", views.employee_remove, name="employee_remove"),
    path("employees/role/", views.role_assign, name="role_assign"),
    path("employees/<str:shift>/", views.shift_detail, name="shift_detail"),
    # Equipment
    path("equipment/", views.equipment_index, name="equipment_index"),
    path("equipment/add/", views.equipment_add, name="equipment_add"),
    path("equipment/remove/", views.equipment_remove, name="equipment_remove"),
    path("equipment/<int:pk>/", views.equipment_detail, name="equipment_detail"),
    path("equipment/train/", views.training_add, name="training_add"),
    path("equipment/untrain/", views.training_remove, name="training_remove"),
]
