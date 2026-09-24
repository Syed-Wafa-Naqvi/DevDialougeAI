from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from accounts.models import Profile

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile'

class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'get_plan', 'get_verified', 'is_active', 'is_staff')

    def get_plan(self, instance):
        return instance.profile.plan if hasattr(instance, 'profile') else '-'
    get_plan.short_description = 'Plan'

    def get_verified(self, instance):
        return instance.profile.is_verified if hasattr(instance, 'profile') else False
    get_verified.short_description = 'OTP Verified'
    get_verified.boolean = True

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'is_verified', 'otp', 'otp_created_at')
    list_filter = ('is_verified', 'plan')
    search_fields = ('user__username', 'user__email')
    list_editable = ('is_verified',)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
