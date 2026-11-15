const PROFILE_NAMES = [
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

const profileRank = new Map(PROFILE_NAMES.map((name, index) => [name.toLowerCase(), index]));

export function orderProfiles(profiles) {
  return [...profiles].sort((a, b) => {
    const aName = (a.name ?? "").trim();
    const bName = (b.name ?? "").trim();
    const aRank = profileRank.get(aName.toLowerCase()) ?? PROFILE_NAMES.length;
    const bRank = profileRank.get(bName.toLowerCase()) ?? PROFILE_NAMES.length;
    return aRank - bRank || aName.localeCompare(bName);
  });
}
