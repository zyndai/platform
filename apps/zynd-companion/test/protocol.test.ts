import { describe, expect, it } from "vitest";
import { FROM_EXTENSION, FROM_PAGE, readPageMessage } from "../src/protocol";

const state = "a".repeat(32);
const token = "zdc_" + "A1b2C3d4".repeat(5);
const grant = { source: FROM_PAGE, type: "grant", state, token, profile: { handle: "dil", name: "Dil", card_url: "https://cards.test/p/dil" } };

describe("readPageMessage", () => {
  it("accepts hello and a complete grant", () => {
    expect(readPageMessage({ source: FROM_PAGE, type: "hello" })).toEqual({ source: FROM_PAGE, type: "hello" });
    expect(readPageMessage(grant)).toMatchObject({ type: "grant", state, token, profile: { handle: "dil", name: "Dil" } });
  });

  it("ignores everything that is not from the connect page", () => {
    for (const junk of [null, undefined, "x", 3, [], {}, { source: FROM_EXTENSION, type: "hello" }, { source: "other", type: "grant" }]) {
      expect(readPageMessage(junk)).toBeNull();
    }
  });

  it("refuses a grant with a bad state, token or profile", () => {
    expect(readPageMessage({ ...grant, state: "short" })).toBeNull();
    expect(readPageMessage({ ...grant, state: "G".repeat(32) })).toBeNull();
    expect(readPageMessage({ ...grant, token: "eyJhbGciOiJFUzI1NiJ9.e30.sig" })).toBeNull();
    expect(readPageMessage({ ...grant, token: "zdc_short" })).toBeNull();
    expect(readPageMessage({ ...grant, profile: null })).toBeNull();
    expect(readPageMessage({ ...grant, profile: { name: "x" } })).toBeNull();
  });
});
