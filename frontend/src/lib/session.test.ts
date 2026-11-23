import { describe, expect, it } from "vitest";
import { scopeRequest, authHeaders, isAuthError, describeApiError, NO_MEMBERSHIP_MESSAGE } from "./session";

describe("authHeaders", () => {
  it("adds a bearer token from the session", () => {
    expect(authHeaders({ access_token: "tok" })).toEqual({ Authorization: "Bearer tok" });
  });
  it("is empty without a session and never sends a machine key", () => {
    expect(authHeaders(null)).toEqual({});
    expect(authHeaders(undefined)).toEqual({});
    expect(Object.keys(authHeaders({ access_token: "t" }))).not.toContain("x-api-key");
  });
});

describe("isAuthError", () => {
  it("is true only for 401", () => {
    expect(isAuthError({ status: 401 })).toBe(true);
    expect(isAuthError({ status: 403 })).toBe(false);
    expect(isAuthError({ status: 503 })).toBe(false);
    expect(isAuthError({ status: 200 })).toBe(false);
  });
});

describe("describeApiError", () => {
  it("explains missing membership on /factory 404", () => {
    expect(describeApiError(404, "/api/v1/factory", "x")).toBe(NO_MEMBERSHIP_MESSAGE);
    expect(NO_MEMBERSHIP_MESSAGE).toContain("python -m app.admin add-member");
  });
  it("shows backend detail on 403", () => {
    expect(describeApiError(403, "/api/v1/reset", "Role viewer cannot do this")).toBe("Role viewer cannot do this");
  });
  it("reports auth outage on 503", () => {
    expect(describeApiError(503, "/api/v1/state", undefined)).toBe("Service temporarily unavailable, retrying");
  });
  it("falls back to detail or null", () => {
    expect(describeApiError(500, "/api/v1/state", "boom")).toBe("boom");
    expect(describeApiError(500, "/api/v1/state", undefined)).toBeNull();
  });
});

describe("scopeRequest", () => {
  it("adds factory_id to the query, keeping an existing one", () => {
    expect(scopeRequest("/api/v1/lines", undefined, "f1").path).toBe("/api/v1/lines?factory_id=f1");
    expect(scopeRequest("/api/v1/x?a=1", undefined, "f1").path).toBe("/api/v1/x?a=1&factory_id=f1");
    expect(scopeRequest("/api/v1/factory/settings?factory_id=demo", undefined, "f1").path).toBe("/api/v1/factory/settings?factory_id=demo");
  });
  it("does nothing without a selection or for unscoped routes", () => {
    expect(scopeRequest("/api/v1/lines", undefined, null).path).toBe("/api/v1/lines");
    expect(scopeRequest("/api/v1/factories", "{}", "f1")).toEqual({ path: "/api/v1/factories", body: "{}" });
    expect(scopeRequest("/api/v1/my/factories", undefined, "f1").path).toBe("/api/v1/my/factories");
  });
  it("merges factory_id into the body of body routes only", () => {
    expect(scopeRequest("/api/v1/reset", undefined, "f1").body).toBe('{"factory_id":"f1"}');
    expect(scopeRequest("/api/v1/reset", '{"factory_id":"demo"}', "f1").body).toBe('{"factory_id":"demo"}');
    expect(scopeRequest("/api/v1/ingest/erp-csv", '{"csv_content":"a"}', "f1").body).toBe('{"csv_content":"a","factory_id":"f1"}');
    expect(scopeRequest("/api/v1/lines", '{"name":"A"}', "f1").body).toBe('{"name":"A"}');
  });
});
