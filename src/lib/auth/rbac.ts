/**
 * Role-Based Access Control (RBAC) Source of Truth
 *
 * Defines Twin AI roles, permissions, route access rules, and default landing pages.
 */

export type ClerkOrgRole =
  | "org:admin"
  | "org:member"
  | "org:supervisor"
  | "org:plant_manager"
  | "org:leadership";

export type FeatureIdentifier =
  | "overview"
  | "liveTwin"
  | "vehicles"
  | "alerts"
  | "flow"
  | "quality"
  | "analytics"
  | "validation"
  | "leadership"
  | "roi"
  | "settings";

type RouteRule = {
  path: string;
  exact: boolean;
};

// Central mapping of allowed route structures for each role
const ROLE_RULES: Record<Exclude<ClerkOrgRole, "org:admin" | "org:member">, RouteRule[]> = {
  "org:supervisor": [
    { path: "/app", exact: true },
    { path: "/app/live-twin", exact: false },
    { path: "/app/vehicles", exact: false },
    { path: "/app/alerts", exact: false },
    { path: "/app/flow", exact: false },
    { path: "/app/quality", exact: false },
  ],
  "org:plant_manager": [
    { path: "/app", exact: true },
    { path: "/app/live-twin", exact: false },
    { path: "/app/vehicles", exact: false },
    { path: "/app/alerts", exact: false },
    { path: "/app/flow", exact: false },
    { path: "/app/quality", exact: false },
    { path: "/app/analytics", exact: false },
    { path: "/app/validation", exact: false },
  ],
  "org:leadership": [
    { path: "/app/analytics", exact: false },
    { path: "/app/leadership", exact: false },
    { path: "/app/roi", exact: false },
  ],
};

/**
 * Checks if a given organization role is allowed to access a specific route pathname.
 */
export function canAccessRoute(role: ClerkOrgRole, pathname: string): boolean {
  // Normalize pathname: remove query string, hash, and trailing slashes (except root)
  let cleanPath = pathname.split("?")[0].split("#")[0];
  if (cleanPath.endsWith("/") && cleanPath.length > 1) {
    cleanPath = cleanPath.slice(0, -1);
  }

  // org:admin holds superuser access to all /app routes
  if (role === "org:admin") {
    return cleanPath === "/app" || cleanPath.startsWith("/app/");
  }

  // org:member is authenticated but holds no stakeholder role by default
  if (role === "org:member") {
    return false;
  }

  const rules = ROLE_RULES[role];
  if (!rules) {
    return false;
  }

  return rules.some((rule) => {
    if (rule.exact) {
      return cleanPath === rule.path;
    }
    // Prefix match ensuring clean path nesting boundary (e.g. /app/live-twin matches /app/live-twin/stations/S18 but not /app/live-twin-extra)
    return cleanPath === rule.path || cleanPath.startsWith(rule.path + "/");
  });
}

/**
 * Returns the default landing page destination for a given role.
 */
export function getDefaultRouteForRole(role: ClerkOrgRole): string | null {
  switch (role) {
    case "org:admin":
      return "/app";
    case "org:supervisor":
      return "/app";
    case "org:plant_manager":
      return "/app/analytics";
    case "org:leadership":
      return "/app/leadership";
    case "org:member":
    default:
      return null;
  }
}

/**
 * Checks if a given role is one of the three operational business stakeholder roles.
 */
export function isStakeholderRole(role: ClerkOrgRole): boolean {
  return role === "org:supervisor" || role === "org:plant_manager" || role === "org:leadership";
}

/**
 * Checks if a given role is the admin superuser role.
 */
export function isAdminRole(role: ClerkOrgRole): boolean {
  return role === "org:admin";
}
