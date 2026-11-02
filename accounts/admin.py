from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from .models import RegistrationSource, ReputationEvent, ReputationNetwork, User
from .services import can_review_participants, review_participant

@admin.register(User)
class ParticipantAdmin(UserAdmin):
    list_display = UserAdmin.list_display + ('participant_status', 'registration_source', 'participant_reviewed_at', 'email_verified')
    list_filter = UserAdmin.list_filter + ('participant_status', 'registration_source', 'email_verified')
    readonly_fields = ('participant_status', 'registration_source', 'participant_reviewed_by', 'participant_reviewed_at', 'email_verified')
    fieldsets = UserAdmin.fieldsets + (('Participation', {'fields': ('participant_status', 'registration_source', 'participant_reviewed_by', 'participant_reviewed_at', 'default_request_visibility', 'default_body_visibility', 'email_verified')}),)
    actions = ('approve_participants', 'reject_participants', 'suspend_participants')

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            fields += ('is_staff', 'is_superuser', 'is_active', 'groups', 'user_permissions')
        return fields

    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_review_permission(self, request):
        return can_review_participants(request.user)

    @transaction.atomic
    def _review(self, request, queryset, status):
        if not self.has_review_permission(request):
            raise PermissionDenied
        count = 0
        for participant_id in queryset.values_list('pk', flat=True):
            participant = review_participant(reviewer=request.user, participant_id=participant_id, status=status)
            self.log_change(request, participant, 'Participant status set to ' + status)
            count += 1
        self.message_user(request, f'{count} account(s) marked {status}.')

    @admin.action(permissions=['review'], description='Approve selected participants')
    def approve_participants(self, request, queryset):
        self._review(request, queryset, 'approved')

    @admin.action(permissions=['review'], description='Reject selected participants')
    def reject_participants(self, request, queryset):
        self._review(request, queryset, 'rejected')

    @admin.action(permissions=['review'], description='Suspend selected participants')
    def suspend_participants(self, request, queryset):
        self._review(request, queryset, 'suspended')

@admin.register(RegistrationSource)
class RegistrationSourceAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'is_active', 'expires_at')
    list_filter = ('is_active',)
    search_fields = ('code', 'label')

@admin.register(ReputationNetwork)
class ReputationNetworkAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')
    search_fields = ('name', 'description')

@admin.register(ReputationEvent)
class ReputationEventAdmin(admin.ModelAdmin):
    list_display = ('user', 'reason', 'reputation', 'letter', 'network', 'created_at')
    list_filter = ('reason', 'network')
    search_fields = ('user__username', 'letter__code')
