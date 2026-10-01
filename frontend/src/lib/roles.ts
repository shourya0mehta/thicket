import type { Role } from '../api/generated';

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, manager: 2, owner: 3 };

export const ROLE_LABEL: Record<Role, string> = {
  owner: 'Owner',
  manager: 'Manager',
  reviewer: 'Reviewer',
  viewer: 'Viewer',
};

export const ROLE_HELP: Record<Role, string> = {
  owner: 'Everything, including members, roles and deleting the organization.',
  manager: 'Sites, recorders, uploads, alert rules and invites.',
  reviewer: 'Review detections, handle alerts and build reports.',
  viewer: 'Read-only access to everything.',
};

export const ROLES: Role[] = ['owner', 'manager', 'reviewer', 'viewer'];

export function atLeast(role: Role | null | undefined, required: Role): boolean {
  if (!role) return false;
  return RANK[role] >= RANK[required];
}

export interface Permissions {
  role: Role | null;
  isOwner: boolean;
  canManage: boolean;
  canReview: boolean;
  canView: boolean;
}

export function permissionsFor(role: Role | null | undefined): Permissions {
  return {
    role: role ?? null,
    isOwner: atLeast(role, 'owner'),
    canManage: atLeast(role, 'manager'),
    canReview: atLeast(role, 'reviewer'),
    canView: atLeast(role, 'viewer'),
  };
}
