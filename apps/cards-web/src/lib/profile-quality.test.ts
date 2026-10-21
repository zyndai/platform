import assert from "node:assert/strict";
import { test } from "node:test";
import { cardDeclarations, cleanTopic, publicTopics } from "./profile-quality";

test("metadata keeps real short topics and excludes narrative and placeholders", () => {
  assert.deepEqual(publicTopics([{ name: "general" }, { name: "Python" }, { name: "python" }], [
    { type: "has_expertise_in", text: "Next.js" },
    { type: "is_learning", text: "Founder of Example, a developer community" },
    { type: "is_learning", text: "I have a long biography. It describes my past achievements." },
  ]), ["Python", "Next.js"]);
  assert.equal(cleanTopic("Developer Relations"), "Developer Relations");
});

test("claiming a card never declares interests as learning", () => {
  const card = { working_on: ["My startup"], can_help_with: ["general"], love_talking_about: ["History", "Books"], skills: [{ name: "Python" }], identity: { location: "Delhi" } };
  assert.deepEqual(cardDeclarations(card), [
    { predicate: "is_building", value: "My startup" },
    { predicate: "has_expertise_in", value: "Python" },
    { predicate: "is_located_in", value: "Delhi" },
  ]);
});
