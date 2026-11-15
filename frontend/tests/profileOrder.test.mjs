import assert from "node:assert/strict";
import { test } from "node:test";
import { orderProfiles } from "../src/lib/profileOrder.js";

test("profile order follows the requested board sequence and sorts other names after it", () => {
  const requested = [
    "Lakshita Madhavan",
    "Stephanie Nicolaescu",
    "Anne Therese Argonza",
    "Sharanya Raj",
    "Saidarsha Karunakaran",
    "Garima Thapa",
    "Carlin Verano",
    "Manisha Palaniappan",
    "Caithy Liao",
    "Azka Faisal",
    "Priya Patel",
    "Meera James",
    "Diya Pottangadi",
  ];
  const profiles = [...requested, "Zoe Example", "Avery Example"]
    .reverse()
    .map((name) => ({ name }));
  const originalNames = profiles.map((profile) => profile.name);

  assert.deepEqual(orderProfiles(profiles).map((profile) => profile.name), [
    ...requested,
    "Avery Example",
    "Zoe Example",
  ]);
  assert.deepEqual(profiles.map((profile) => profile.name), originalNames);
});
