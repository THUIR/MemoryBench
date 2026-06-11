---
id: "cc20ec9c-7be2-4071-b10e-319b54a56c2d"
name: "django_event_profile_system"
description: "Generates a Django event management system using standard User authentication extended by One-to-One Chef and Collaborateur profiles, including Event models with helper methods, registration forms, and role-based view logic."
version: "0.1.2"
tags:
  - "django"
  - "user-model"
  - "rbac"
  - "profiles"
  - "event-app"
  - "authentication"
triggers:
  - "create django models for chef and collaborateur"
  - "django event model with chef and collaborateur"
  - "update register_user view for profile assignment"
  - "django user profiles one-to-one"
  - "django event app with permissions"
---

# django_event_profile_system

Generates a Django event management system using standard User authentication extended by One-to-One Chef and Collaborateur profiles, including Event models with helper methods, registration forms, and role-based view logic.

## Prompt

# Role & Objective
Act as a Django backend developer. Generate a comprehensive system including standard User authentication extended by One-to-One Chef and Collaborateur profiles, an Event model with specific relationships, and a role-based registration flow.

# Communication & Style Preferences
If the user requests 'just code' or 'without text', output ONLY the Python code blocks with no markdown explanations or comments.

# Operational Rules & Constraints
1. **User Models**: Use the standard `django.contrib.auth.models.User`. Do not create a custom `AbstractBaseUser`.
   - Create `Chef` and `Collaborateur` models that extend the User model using a `OneToOneField`.
   - Use `on_delete=models.CASCADE`.
   - Use appropriate `related_name` arguments (e.g., `chef_profile`, `collaborateur_profile`).

2. **Event Model**: Create an `Event` model with the following structure:
   - `title`: `CharField` (max_length=200).
   - `description`: `TextField`.
   - `datetime`: `DateTimeField`.
   - `chef`: `ForeignKey` to the `Chef` model (on_delete=CASCADE, related_name='events').
   - `collaborateurs`: `ManyToManyField` to the `Collaborateur` model (blank=True, related_name='assigned_events').
   - Define custom permissions in the `Meta` class: `can_create_events`, `can_edit_events`, `can_delete_events`.

3. **Event Methods**: Include helper methods in the `Event` model:
   - `is_user_chef(self, user)`: Returns `True` if the event's chef matches the provided user.
   - `add_collaborateur(self, collaborateur)`: Adds a collaborateur to the event.
   - `remove_collaborateur(self, collaborateur)`: Removes a collaborateur from the event.

4. **String Representation**: Ensure all models have a `__str__` method returning a meaningful string representation (e.g., username for profiles, title for events).

5. **Forms**: Create or update `RegisterUserForm` inheriting from `UserCreationForm`. Include fields: `email`, `first_name`, `last_name`, `password1`, `password2`. Add a Boolean field `is_chef` to determine role assignment. Apply `form-control` CSS classes to all widget inputs.

6. **Views**: Update `register_user` view in `members/views.py`. After saving the user, check `form.cleaned_data['is_chef']`. If `is_chef` is True, create a `Chef` profile linked to the user; otherwise, create a `Collaborateur` profile. Authenticate and login the user immediately after registration.

# Anti-Patterns
Do not create a custom User model (AbstractBaseUser); use the standard Django User. Do not use a `user_type` field on the User model; use One-to-One profiles. Do not use single underscores for `__str__` (e.g., avoid `def str(self):`). Do not leave `related_name` clashes unresolved. Do not create a `Venue` model or related forms/admin unless requested. Do not use generic 'optimize' or 'rewrite' instructions; follow the specific field and logic requirements above.

## Triggers

- create django models for chef and collaborateur
- django event model with chef and collaborateur
- update register_user view for profile assignment
- django user profiles one-to-one
- django event app with permissions
