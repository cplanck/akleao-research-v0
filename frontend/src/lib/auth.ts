/**
 * Auth API client for magic link authentication.
 * Uses httpOnly cookies - no token storage needed in frontend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface User {
  id: string;
  email: string;
  name: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: User;
}

/**
 * Request a magic link email.
 */
export async function requestMagicLink(email: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/magic-link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to send magic link" }));
    throw new Error(error.detail || "Failed to send magic link");
  }
}

/**
 * Verify a magic link token.
 * On success, the server sets an httpOnly cookie.
 */
export async function verifyMagicLink(token: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ token }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Invalid or expired link" }));
    throw new Error(error.detail || "Invalid or expired link");
  }

  return res.json();
}

/**
 * Get the current authenticated user.
 * Returns null if not authenticated.
 */
export async function getCurrentUser(): Promise<User | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      credentials: "include",
    });

    if (!res.ok) {
      if (res.status === 401) {
        return null;
      }
      throw new Error("Failed to get user");
    }

    return res.json();
  } catch {
    return null;
  }
}

/**
 * Update user profile.
 */
export async function updateProfile(name: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ name }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to update profile" }));
    throw new Error(error.detail || "Failed to update profile");
  }

  return res.json();
}

/**
 * Logout - clears the auth cookie.
 */
export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Ignore errors - we'll clear local state anyway
  }
}
