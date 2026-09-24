from django.contrib import admin
from chat.models import Session, Message, GeneratedCode

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'mode', 'status', 'started_at')
    list_filter = ('mode', 'status')
    search_fields = ('title', 'user__username')

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'timestamp')
    list_filter = ('role',)
    search_fields = ('content', 'session__title')

@admin.register(GeneratedCode)
class GeneratedCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'module_name', 'session', 'generated_at')
    search_fields = ('module_name', 'code_content')
