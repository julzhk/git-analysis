from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('analyses/step/repo/', views.step_repo, name='step_repo'),
    path('analyses/inspect/', views.inspect_repo, name='inspect_repo'),
    path('analyses/', views.create_analysis, name='create_analysis'),
    path('analyses/<uuid:pk>/', views.analysis_detail, name='analysis_detail'),
    path('analyses/<uuid:pk>/delete/', views.delete_analysis, name='delete_analysis'),
    path('analyses/<uuid:pk>/rerun/', views.rerun_analysis, name='rerun_analysis'),
    path('analyses/<uuid:pk>/progress/', views.analysis_progress, name='analysis_progress'),
    path('analyses/<uuid:pk>/files/table/', views.files_table, name='files_table'),
    path('analyses/<uuid:pk>/files/detail/', views.file_detail, name='file_detail'),
    path('analyses/<uuid:pk>/files.csv', views.files_csv, name='files_csv'),
    path('analyses/<uuid:pk>/charts/<slug:name>.png', views.chart, name='chart'),
    path('analyses/<uuid:pk>/<slug:tab>/', views.analysis_detail, name='analysis_tab'),
]
