import { describe, expect, it } from "vitest";
import { clientStatusText } from "./clientStatus";

describe("clientStatusText", () => {
  it("says nothing has been drafted when there is no record", () => {
    expect(clientStatusText(null)).toBe("No extension request yet.");
  });
  it("draft awaits human approval and nothing is sent", () => {
    expect(clientStatusText({ status: "DRAFTED", client: "Volt Motors", extension_hours: 12 })).toBe(
      "Draft: 12h extension request to Volt Motors. Not sent; awaiting human approval."
    );
  });
  it("sent request awaits the client's answer", () => {
    expect(clientStatusText({ status: "SENT", client: "Volt Motors", extension_hours: 12 })).toBe(
      "Sent to Volt Motors; awaiting their answer."
    );
  });
  it("answering is an in-progress re-plan", () => {
    expect(clientStatusText({ status: "ANSWERING", client: "Volt Motors", extension_hours: 12 })).toBe(
      "Answer recorded; re-planning is in progress. Submit the same answer again to resume if it stalls."
    );
  });
  it("accepted shows the new deadline hours", () => {
    expect(
      clientStatusText({ status: "ACCEPTED", client: "Volt Motors", extension_hours: 12, replan_deadline_hours: 60 })
    ).toBe("Volt Motors accepted; deadline now 60h. Re-planned.");
  });
  it("refused says expedite is allowed again", () => {
    expect(clientStatusText({ status: "REFUSED", client: "Volt Motors", extension_hours: 12 })).toBe(
      "Volt Motors refused the extension. Re-planned with the original deadline."
    );
  });
});
