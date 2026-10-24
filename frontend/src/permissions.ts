import type { User } from "./types";

// Current servers return permissions. The fallback only supports the original
// role contract for older deployments; unknown roles receive no privileges.
const legacyPermissions: Record<string, string[]> = {
  owner: ["*"],
  admin: [
    "appointment:read",
    "appointment:write",
    "task:read",
    "task:write",
    "policy:read",
    "policy:write",
    "catalog:read",
    "catalog:write",
    "billing:read",
    "billing:write",
    "privacy:manage",
    "integration:read",
    "integration:write",
    "routing:write",
    "audit:read",
    "building:read",
    "reports:read",
    "health:read",
  ],
  receptionist: [
    "appointment:read",
    "appointment:write",
    "task:read",
    "task:write",
    "policy:read",
    "catalog:read",
    "billing:read",
    "billing:write",
    "integration:read",
  ],
  clinician: [
    "appointment:read",
    "appointment:write",
    "task:read",
    "task:write",
    "policy:read",
    "catalog:read",
    "integration:read",
  ],
  partner: [],
};

export function hasPermission(
  user: Pick<User, "role" | "permissions">,
  permission: string,
) {
  const permissions = user.permissions ?? legacyPermissions[user.role] ?? [];
  return permissions.includes("*") || permissions.includes(permission);
}

export const roleNames: Record<string, string> = {
  owner: "مالک مرکز",
  admin: "مدیر سامانه",
  manager: "مدیر مرکز",
  coordinator: "هماهنگ‌کننده",
  receptionist: "تیم پذیرش",
  clinician: "پزشک / ارائه‌دهنده",
  billing: "امور مالی",
  technical: "پشتیبانی فنی",
  partner: "همکار تجاری",
};
