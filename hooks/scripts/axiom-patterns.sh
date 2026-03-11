#!/usr/bin/env bash
# axiom-patterns.sh — T0 violation patterns for axiom governance
# Sourced by axiom-scan.sh and axiom-commit-scan.sh
# Single source of truth for all structural multi-user scaffolding patterns.

AXIOM_PATTERNS=(
  # su-auth-001: Auth/authz scaffolding
  'class User(Manager|Service|Repository|Controller|Model)\b'
  'class Auth(Manager|Service|Handler)\b'
  'class (Role|Permission|ACL|RBAC|OAuth|Session)Manager\b'
  'def (authenticate|authorize|login|logout|register)_user'
  'def (create|delete|update|list)_users?\b'
  'def check_permission'
  'from (django\.contrib\.auth|flask_login|passlib|bcrypt) import'

  # su-feature-001: Multi-user collaboration
  'class (CollaborationManager|SharingService|MultiUserSync)\b'
  'class MultiTenant'
  'class Tenant(Manager|Service|Config)\b'

  # su-privacy-001: Privacy/consent scaffolding
  'class (ConsentManager|PrivacyPolicy|DataAnonymizer|GDPR)\b'

  # su-security-001: Multi-tenant security
  'class (RateLimiter|UserQuota|AbusePrevention)\b'
  'user_roles\b|role_assignment\b|permission_check\b'

  # su-admin-001: Admin interfaces
  'class (AdminPanel|AdminDashboard|UserAdmin)\b'

  # mg-boundary-001 / mg-boundary-002: Management feedback generation
  'def (generate|draft|write|compose)_feedback'
  'def (suggest|recommend)_.*to_say'
  'class FeedbackGenerator\b'
  'class CoachingRecommender\b'
)
