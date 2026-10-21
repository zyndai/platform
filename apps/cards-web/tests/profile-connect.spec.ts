import { expect, test, type Page } from "@playwright/test";
import type { CardConnection } from "../src/lib/cards-network";
import { mockNetwork } from "./fixtures/network";
import { signIn } from "./fixtures/sign-in";

/**
 * The Connect / Message button in the purple hero of a claimed Card: it asks the API where the
 * viewer stands and offers the one action that can work.
 */

const CONNECTION_ID = "44444444-4444-4444-8444-444444444444";

function connectionTo(handle: string, overrides: Partial<CardConnection> = {}): CardConnection {
  return {
    id: CONNECTION_ID, status: "pending", incoming: false, created_at: new Date().toISOString(),
    partner: { card_id: `${handle}-card`, handle, name: "Alice Chen" },
    thread_id: null, last_message_at: null, last_message_preview: null, last_message_sender_user_id: null,
    unread_count: 0, ...overrides,
  };
}

const hero = (page: Page) => page.locator(".pf-hero");
const pill = (page: Page, name: string) => hero(page).getByRole("button", { name, exact: true });

test("signed-out visitors get a Connect link that brings them back to the profile", async ({ page }) => {
  await page.goto("/p/claimed");
  const connect = hero(page).getByRole("link", { name: "Connect", exact: true });
  await expect(connect).toBeVisible();
  const href = await connect.getAttribute("href");
  expect(href).toBe("/auth?next=%2Fp%2Fclaimed");
  expect(new URL(href!, "http://x").searchParams.get("next")).toBe("/p/claimed");
});

test("the button is a white pill directly under the name, inside the hero", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/p/claimed");

  const connect = pill(page, "Connect");
  await expect(connect).toBeVisible();
  await expect(connect).toBeEnabled();
  const [name, button, card] = await Promise.all([
    hero(page).locator(".pf-hero-name").boundingBox(),
    connect.boundingBox(),
    hero(page).boundingBox(),
  ]);
  expect(button!.y).toBeGreaterThanOrEqual(name!.y + name!.height);      // below the name line...
  expect(button!.y).toBeLessThan(name!.y + name!.height + 40);            // ...right under it
  expect(Math.abs(button!.x - name!.x)).toBeLessThanOrEqual(1);           // in the name column
  expect(button!.x + button!.width).toBeLessThanOrEqual(card!.x + card!.width);
  expect(await connect.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 255, 255)");

  // and it is no longer the near-invisible control above the page header
  await expect(page.locator(".pf-connect")).toHaveCount(1);
  await expect(hero(page).locator(".pf-connect")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Request connection" })).toHaveCount(0);
});

test("Connect opens a popover; a failed send keeps the note, a retry makes the pill Requested", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.failNextRequest = true;
  await page.goto("/p/claimed");

  await pill(page, "Connect").click();
  const dialog = page.getByRole("dialog", { name: "Connect with Alice Chen" });
  await expect(dialog).toBeVisible();
  await expect(pill(page, "Connect")).toHaveAttribute("aria-expanded", "true");
  await dialog.getByLabel("Connection note").fill("Can we discuss APIs?");
  await dialog.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Temporarily unavailable");
  await expect(dialog.getByLabel("Connection note")).toHaveValue("Can we discuss APIs?");

  await dialog.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(pill(page, "Requested")).toHaveAttribute("aria-disabled", "true");
  await expect(hero(page).getByRole("status")).toHaveText("Connection request sent");
  expect(state.connections.at(-1)?.request_message).toBe("Can we discuss APIs?");
  expect(state.connections.at(-1)?.partner.handle).toBe("claimed");

  // a reload asks the API again and still says Requested
  await page.reload();
  await expect(pill(page, "Requested")).toBeVisible();
});

test("Escape and Cancel close the popover and hand focus back to the pill", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/p/claimed");

  await pill(page, "Connect").click();
  const dialog = page.getByRole("dialog", { name: "Connect with Alice Chen" });
  await expect(dialog.getByLabel("Connection note")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(pill(page, "Connect")).toBeFocused();

  await pill(page, "Connect").click();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);

  await pill(page, "Connect").click();
  await page.mouse.click(5, 400);                   // outside
  await expect(dialog).toHaveCount(0);
});

test("a request waiting for you is accepted in place and turns into Message", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionTo("claimed", { incoming: true }));
  await page.goto("/p/claimed");

  await expect(hero(page).getByText("Alice Chen wants to connect with you.")).toBeVisible();
  await pill(page, "Accept").click();
  const message = hero(page).getByRole("link", { name: "Message", exact: true });
  await expect(message).toHaveAttribute("href", `/network?c=${CONNECTION_ID}`);
  await expect(hero(page).getByRole("status")).toHaveText("Connection accepted");
  expect(state.connections.find((row) => row.id === CONNECTION_ID)?.status).toBe("accepted");
});

test("an accepted connection shows Message, which opens that conversation", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionTo("claimed", { status: "accepted", thread_id: "66666666-6666-4666-8666-666666666666" }));
  await page.goto("/p/claimed");

  const message = hero(page).getByRole("link", { name: "Message", exact: true });
  await expect(message).toHaveAttribute("href", `/network?c=${CONNECTION_ID}`);
  await expect(hero(page).getByRole("button", { name: "Connect" })).toHaveCount(0);
  await message.click();
  await expect(page).toHaveURL(new RegExp(`/network\\?c=${CONNECTION_ID}`));
});

test("without a Card of your own the button is disabled and says why, with a way to get one", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.viewerHasCard = false;
  await page.goto("/p/claimed");

  const connect = pill(page, "Connect");
  await expect(connect).toHaveAttribute("aria-disabled", "true");
  await expect(connect).toHaveAttribute("title", "Claim and publish your own Card to connect with people.");
  await expect(hero(page).getByText("Claim and publish your own Card to connect with people.")).toBeVisible();
  await expect(hero(page).getByRole("link", { name: "Create your Card" })).toHaveAttribute("href", "/create");
  await connect.click({ force: true });             // aria-disabled: clickable, but nothing opens
  await expect(page.getByRole("dialog", { name: /Connect with/ })).toHaveCount(0);
});

test("a declined request cannot be sent again, and the button says so", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionTo("claimed", { status: "declined" }));
  await page.goto("/p/claimed");

  const connect = pill(page, "Connect");
  await expect(connect).toHaveAttribute("aria-disabled", "true");
  await expect(hero(page).getByText("This request was not accepted.")).toBeVisible();
  await expect(hero(page).getByRole("link", { name: "Create your Card" })).toHaveCount(0);
  await connect.click({ force: true });             // aria-disabled: clickable, but nothing opens
  await expect(page.getByRole("dialog", { name: /Connect with/ })).toHaveCount(0);
});

test("if the status call fails, Connect still works and the request reports what is true", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionTo("claimed", { status: "accepted" }));
  state.failNextStatus = true;
  await page.goto("/p/claimed");

  await pill(page, "Connect").click();
  await page.getByRole("dialog", { name: "Connect with Alice Chen" }).getByRole("button", { name: "Send request", exact: true }).click();
  await expect(hero(page).getByRole("status")).toHaveText("You are already connected");
  await expect(hero(page).getByRole("link", { name: "Message", exact: true })).toHaveAttribute("href", `/network?c=${CONNECTION_ID}`);
});

test("your own card and unclaimed cards have no button", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/p/owner");
  await expect(page.getByRole("link", { name: /Edit/ }).first()).toBeVisible();
  await expect(page.locator(".pf-connect")).toHaveCount(0);

  // the owner previewing their card as a visitor: the API says it is their own, so still nothing
  await page.goto("/p/owner?preview=visitor");
  await expect(hero(page)).toBeVisible();
  await expect(page.locator(".pf-connect-pill")).toHaveCount(0);

  await page.goto("/p/unclaimed");
  await expect(page.locator(".pf-connect")).toHaveCount(0);
});

test("on a phone the pill fits, and the popover stays on screen", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/p/claimed");

  const connect = pill(page, "Connect");
  await expect(connect).toBeVisible();
  const button = await connect.boundingBox();
  expect(button!.height).toBeGreaterThanOrEqual(40);
  expect(button!.x + button!.width).toBeLessThanOrEqual(390);

  await connect.click();
  const dialog = page.getByRole("dialog", { name: "Connect with Alice Chen" });
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test.describe("on a limited-edition card", () => {
  test.beforeEach(async ({ request }) => {
    await request.post("http://127.0.0.1:3030/__s10/reset");
  });
  test.afterEach(async ({ request }) => {
    await request.post("http://127.0.0.1:3030/__s10/reset");
  });

  async function pickEdition(page: Page) {
    await page.goto("/p/owner/edit");
    const style = page.locator("#style");
    await style.getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await style.getByRole("button", { name: "Speaking", exact: true }).click();
    await page.getByRole("button", { name: "Save changes" }).first().click();
    await expect(page.getByText("Changes saved", { exact: true })).toBeVisible();
  }

  test("the button leads the actions of the identity card, in the edition accent", async ({ page, context }) => {
    await signIn(context);
    await pickEdition(page);
    const state = await mockNetwork(page);
    state.selfHandle = "";                       // view the owner's card as a visitor would
    await page.goto("/p/owner?preview=visitor");

    const side = page.locator(".ed-id-side");
    const connect = side.getByRole("button", { name: "Connect", exact: true });
    await expect(connect).toBeVisible();
    await expect(page.locator(".pf-hero")).toHaveCount(0);
    const chat = side.getByRole("button", { name: /Open chat/ });
    expect((await connect.boundingBox())!.y).toBeLessThan((await chat.boundingBox())!.y);
    expect(await connect.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(108, 92, 231)");
  });

  test("signed out it is a sign-in link, and on a phone it spans the actions", async ({ page, context }) => {
    await signIn(context);
    await pickEdition(page);
    await context.clearCookies();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/p/owner?preview=visitor");

    const connect = page.locator(".ed-id-side").getByRole("link", { name: "Connect", exact: true });
    await expect(connect).toHaveAttribute("href", "/auth?next=%2Fp%2Fowner");
    const [button, side] = await Promise.all([connect.boundingBox(), page.locator(".ed-id-side").boundingBox()]);
    expect(button!.width).toBeGreaterThan(side!.width - 4);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});
