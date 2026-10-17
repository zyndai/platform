import { describe, expect, it } from "vitest";
import { pluginScopes, requireScope } from "../src/consent.js";

const EXACT = ["memory:recall", "memory:propose", "cards:review"];

describe("plugin scope guards", () => {
  it("accepts only the exact ChatGPT plugin grant", () => {
    expect(pluginScopes(EXACT)).toEqual(EXACT);
  });

  it("rejects legacy and partial grants", () => {
    expect(() => pluginScopes(["user"])).toThrow();
    expect(() => pluginScopes(["memory:read", "memory:write", "card:read", "card:write"])).toThrow();
    expect(() => pluginScopes(["memory:recall", "memory:propose"])).toThrow();
    expect(() => pluginScopes([...EXACT, "people:message"])).toThrow();
  });

  it("checks the tool scope", () => {
    expect(() => requireScope(EXACT, "memory:recall")).not.toThrow();
    expect(() => requireScope(EXACT, "memory:write")).toThrow();
  });
});
