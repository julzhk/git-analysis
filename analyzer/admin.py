from django.contrib import admin

from .models import Analysis


@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = ("repo_name", "branch", "status", "stage", "created_at", "finished_at")
    list_filter = ("status",)
    readonly_fields = ("results",)
