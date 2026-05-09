from django.urls import path
from . import views

app_name = 'maintabs'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('reports/', views.reports, name='reports'),
    path('notifications/', views.notifications, name='notifications'),
    path('join/', views.join_account, name='join_account'),
    path('notifications/join-request/<int:pk>/<str:action>/',
        views.handle_join_request,
        name='handle_join_request',
    ),
    path('notifications/<int:pk>/delete/', views.delete_notification, name='delete_notification'),
    path('notifications/clear/', views.clear_notifications, name='clear_notifications'),
    path(
        'notifications/join-request/<int:pk>/dismiss/',
        views.dismiss_join_request,
        name='dismiss_join_request',
    ),
    path('containers/add/', views.add_container, name='add_container'),
    path('containers/<int:pk>/delete/', views.delete_container, name='delete_container'),
    path('goals/add/', views.add_goal, name='add_goal'),
    path('goals/<int:pk>/delete/', views.delete_goal, name='delete_goal'),
    path('operations/add/', views.add_operation, name='add_operation'),
    path('operations/<int:pk>/edit/', views.edit_operation, name='edit_operation'),
    path('operations/<int:pk>/delete/', views.delete_operation, name='delete_operation'),

    path('categories/add/', views.add_category, name='add_category'),
    
    path('plans/', views.plan, name='plan'),
    path('plans/add/', views.add_plan, name='add_plan'),
    path('plans/<int:pk>/edit/', views.edit_plan, name='edit_plan'),
    path('plans/<int:pk>/delete/', views.delete_plan, name='delete_plan')
]