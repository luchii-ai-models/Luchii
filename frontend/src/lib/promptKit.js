// Built-in prompt kit for the /create composer: a large preset pool that rotates, and a
// "Surprise me" generator that builds a fresh prompt every time (never the same demo text).

export const TEXT_PRESETS = [
  { id: "portrait", label: "Portrait", style: "photorealistic", aspect: "3:4", prompt: "Close-up portrait of a young woman with freckles, soft window light, natural skin texture, 85mm lens, shallow depth of field" },
  { id: "landscape", label: "Landscape", style: "cinematic", aspect: "16:9", prompt: "Misty mountain valley at golden hour, layered ridges, warm sun rays through clouds, wide vista" },
  { id: "product", label: "Product shot", style: "product", aspect: "1:1", prompt: "Luxury perfume bottle on wet black marble, soft rim light, water droplets, premium advertising shot" },
  { id: "anime", label: "Anime hero", style: "anime", aspect: "3:4", prompt: "Anime girl with silver hair and a red scarf on a rooftop at sunset, wind in her hair, city skyline behind" },
  { id: "logo", label: "Logo / icon", style: "digital-art", aspect: "1:1", prompt: "Minimal fox head logo icon, bold geometric shapes, flat vector, orange on a clean white background" },
  { id: "scifi", label: "Sci-fi city", style: "3d", aspect: "16:9", prompt: "Futuristic city at night with flying cars, glowing neon signs, rain-slick streets, volumetric light" },
  { id: "food", label: "Food photo", style: "product", aspect: "4:3", prompt: "Stack of fluffy pancakes with berries and dripping maple syrup, morning light, rustic wooden table" },
  { id: "fashion", label: "Fashion", style: "cinematic", aspect: "3:4", prompt: "Fashion editorial of a model in a flowing red dress on a windy beach, overcast light, film look" },
  { id: "pet", label: "Cute pet", style: "photorealistic", aspect: "1:1", prompt: "Golden retriever puppy sitting in autumn leaves, soft afternoon light, detailed fur, happy expression" },
  { id: "fantasy", label: "Fantasy world", style: "digital-art", aspect: "16:9", prompt: "Floating islands with waterfalls above the clouds, giant glowing tree, dragons flying, epic scale" },
  { id: "car", label: "Supercar", style: "3d", aspect: "16:9", prompt: "Sleek matte black supercar in a dark studio, dramatic red rim lighting, reflective floor" },
  { id: "interior", label: "Interior", style: "photorealistic", aspect: "4:3", prompt: "Cozy Scandinavian living room, large window, plants, warm wood, soft daylight, interior design photo" },
  { id: "space", label: "Deep space", style: "cinematic", aspect: "16:9", prompt: "Glowing purple and blue nebula with a bright star cluster, deep space photograph, ultra detailed" },
  { id: "chrome", label: "3D abstract", style: "3d", aspect: "1:1", prompt: "Twisted liquid chrome sculpture with teal reflections on a glossy floor, studio lighting" },
  { id: "street", label: "Street photo", style: "cinematic", aspect: "3:4", prompt: "Rainy Tokyo street at night, person with a clear umbrella, neon reflections on wet pavement" },
  { id: "watercolor", label: "Watercolor", style: "digital-art", aspect: "4:3", prompt: "Watercolor painting of a seaside village with colorful houses, soft washes, loose brush strokes" },
  { id: "character", label: "Game character", style: "3d", aspect: "3:4", prompt: "Stylized armored knight character, full body, glowing blue sword, game concept, clean background" },
  { id: "wedding", label: "Couple", style: "photorealistic", aspect: "3:4", prompt: "Happy couple laughing in a sunflower field at sunset, warm golden light, candid photo" },
];

export const REMIX_PRESETS = [
  { id: "snow", label: "Snowy night", prompt: "make it a snowy winter night" },
  { id: "anime", label: "Anime style", style: "anime", prompt: "turn it into an anime illustration" },
  { id: "sunset", label: "Golden sunset", prompt: "make it golden hour sunset light" },
  { id: "oil", label: "Oil painting", prompt: "turn it into an oil painting" },
  { id: "cyber", label: "Cyberpunk neon", prompt: "make it cyberpunk with neon lights" },
  { id: "spring", label: "Spring flowers", prompt: "add blooming spring flowers" },
  { id: "rain", label: "Rainy mood", prompt: "make it rainy and moody" },
  { id: "sketch", label: "Pencil sketch", prompt: "turn it into a pencil sketch" },
  { id: "3d", label: "3D cartoon", style: "3d", prompt: "turn it into a 3D cartoon character" },
  { id: "autumn", label: "Autumn", prompt: "make it autumn with orange leaves" },
  { id: "vintage", label: "Vintage film", prompt: "make it look like a vintage 1970s photo" },
  { id: "night", label: "Day to night", prompt: "turn day into night with city lights" },
];

const pick = (a) => a[Math.floor(Math.random() * a.length)];
const maybe = (p, v) => (Math.random() < p ? v : "");

// ---------- "Surprise me": a prompt grammar, not a fixed list ----------
// Every click combines a subject, what it is doing, where, when, mood, palette and camera/look.
// That gives hundreds of thousands of distinct prompts; the last 300 (and the last 25 subjects)
// are remembered in localStorage, so the same idea never comes back, even after a reload.
const SUBJECTS = [
  "an old fisherman", "a ballerina", "a red fox", "a lighthouse", "a vintage motorcycle", "a steaming cup of coffee",
  "an astronaut", "a koi pond", "a street food vendor", "a samurai", "a hot air balloon", "a snow leopard",
  "a log cabin", "a jazz saxophonist", "a hummingbird", "a camel caravan", "a glass terrarium", "a futuristic sneaker",
  "a grandmother baking bread", "a grey wolf", "a surfer", "a robot gardener", "a Venetian gondola", "a bowl of ramen",
  "a child with a kite", "a medieval castle", "a chameleon", "a retro arcade", "a giant sea turtle", "a barn owl",
  "a desert nomad", "a tiny mouse chef", "a steam locomotive", "a flamenco dancer", "a Bengal tiger", "an ice cream truck",
  "a treehouse village", "a deep sea diver", "a vintage typewriter", "a mountain goat", "a street musician", "a white peacock",
  "a floating island", "a beekeeper", "a pirate ship", "a blacksmith at the forge", "a polar bear cub", "a neon motorbike rider",
  "a botanist", "a cyborg cat", "a skateboarder", "an ancient temple", "a jellyfish swarm", "a florist",
  "a vintage camper van", "a giant mushroom forest", "a chess grandmaster", "a dragon", "a ramen shop", "a puffin",
  "a tea ceremony", "a mechanical clockwork heart", "a Viking longship", "a parrot", "a ceramic artist", "a racing car",
  "a cozy bookstore", "a whale breaching", "a girl reading in a library", "a firefighter", "a crystal cave", "a hedgehog",
  "a desert cactus in bloom", "an elderly couple dancing", "a lantern festival", "a monk", "a red panda", "a sushi chef",
  "a snowboarder", "a farmer with sheep", "a submarine", "a carousel", "a jaguar", "a violinist", "a windmill",
];
// Generic framing works for any subject; motion lines only for living subjects (no "a lighthouse in mid-motion").
const FRAMING = [
  "", "", "seen from a low angle", "seen from above", "reflected in still water", "framed by an open doorway",
  "half hidden in shadow", "in a close-up shot", "in a wide establishing shot", "silhouetted against the light",
  "surrounded by drifting particles",
];
const LIVING_ACTIONS = ["resting quietly", "in mid-motion", "looking toward the camera", "caught in a gust of wind", "lost in thought", "mid-laugh"];
const LIVING = /\b(fisherman|ballerina|fox|astronaut|vendor|samurai|leopard|saxophonist|hummingbird|camel|grandmother|wolf|surfer|robot|child|chameleon|turtle|owl|nomad|mouse|dancer|tiger|diver|goat|musician|peacock|beekeeper|blacksmith|bear|rider|botanist|cat|skateboarder|jellyfish|florist|grandmaster|dragon|puffin|artist|whale|girl|firefighter|hedgehog|couple|monk|panda|chef|snowboarder|farmer|jaguar|violinist|parrot)\b/i;
// Outdoor places get a time of day or weather; indoor places get a light source instead (no "thunderstorm in a studio").
const OUTDOOR = [
  "on a stormy cliff", "in a bamboo forest", "in a neon-lit alley", "on a misty lake", "by the sea", "in an autumn forest",
  "on a rooftop", "in a snowy village", "in a desert canyon", "in a tropical rainforest", "in a Moroccan market",
  "in a Tokyo side street", "on a lavender field", "in a lunar crater", "on a mountain pass", "in a wheat field",
  "on a frozen lake", "on a Greek island", "in a Scottish highland valley", "in a futuristic megacity",
  "in a cherry blossom park", "on a volcanic beach",
];
const INDOOR = [
  "in a sunlit studio", "in an abandoned greenhouse", "inside a grand library", "in a flooded cathedral",
  "in a busy train station", "in a candle-lit cellar", "in a vintage diner", "in a cozy attic", "in an art deco hotel lobby",
];
const WATER = /\b(koi|turtle|diver|jellyfish|whale|submarine|surfer|gondola|ship|longship)\b/i;
const WATER_PLACES = ["in a coral reef", "in the open ocean", "by the sea", "on a misty lake", "in a Venetian canal", "in a deep blue lagoon"];
const LIGHTS = ["in soft window light", "lit by warm candlelight", "under dramatic spotlights", "in dusty golden light beams",
  "under flickering neon light", "in cool morning light"];
const TIMES = [
  "at golden hour", "at blue hour", "at dawn", "at midnight", "under northern lights", "in morning fog", "in heavy rain",
  "in a snowstorm", "under a starry sky", "at sunset", "on an overcast afternoon", "during a thunderstorm",
  "under a full moon", "in soft spring light", "on a hazy summer noon",
];
const MOODS = ["serene", "dramatic", "dreamy", "nostalgic", "mysterious", "joyful", "epic", "cozy", "melancholic", "whimsical", "tense", "peaceful"];
const PALETTES = [
  "warm amber and gold tones", "cool blue and silver tones", "pastel pink and mint colors", "deep emerald and copper tones",
  "muted earthy tones", "vivid sunset oranges and purples", "black and white with one red accent", "soft cream and sage colors",
  "rich jewel tones", "icy turquoise and white", "crimson and charcoal tones", "golden and teal tones",
];
const LOOKS = {
  photorealistic: ["shot on a 50mm lens", "85mm portrait lens, shallow depth of field", "natural skin and texture detail",
    "soft natural light", "crisp true-to-life colors", "documentary photo", "35mm film grain", "macro detail"],
  cinematic: ["anamorphic film still", "dramatic side light", "wide cinematic framing", "volumetric light rays",
    "film grain and lens flare", "moody color grade", "epic movie scene", "rim lighting"],
  "3d": ["glossy octane render", "soft clay render", "stylized Pixar-like render", "isometric diorama", "low poly scene",
    "miniature tilt-shift diorama", "toy figurine render", "subsurface scattering, studio light"],
  anime: ["Studio Ghibli inspired", "vibrant cel shading", "dynamic anime key visual", "soft pastel anime colors",
    "90s retro anime look", "detailed manga line art, colored", "makoto shinkai style sky", "chibi style"],
  "digital-art": ["vivid fantasy illustration", "watercolor texture", "bold graphic poster", "dreamy matte painting",
    "art nouveau illustration", "ukiyo-e woodblock print style", "synthwave poster", "storybook illustration"],
  product: ["premium studio advertising shot", "clean seamless backdrop", "dramatic product lighting", "minimal luxury styling",
    "floating product with soft shadow", "splash photography", "flat lay composition", "glossy reflections on acrylic"],
};
const PRODUCTS = [
  "a perfume bottle", "a luxury watch", "a pair of headphones", "a sneaker", "a skincare jar", "a coffee bag", "a smartphone",
  "a bottle of craft beer", "a lipstick", "a leather handbag", "a scented candle", "an energy drink can", "a pair of sunglasses",
  "a chocolate bar", "a gaming controller", "a glass teapot", "a mechanical keyboard", "a jar of honey",
];
const PRODUCT_SETS = [
  "on wet black marble", "on a pastel pedestal", "among fresh lemons and mint", "on a bed of moss and stones",
  "with splashing water", "on raw silk fabric", "floating above sand dunes", "between ice cubes", "on a terracotta tile",
  "surrounded by flower petals", "on brushed metal", "in a beam of sunlight",
];

// ---------- remix ideas: verb + target + value ----------
const COLORS = ["electric blue", "pastel pink", "platinum blonde", "fiery red", "emerald green", "lavender purple", "jet black",
  "copper orange", "silver white", "teal", "honey brown", "rainbow ombre"];
const OUTFITS = ["a tailored black suit", "a red evening gown", "a denim jacket and white t-shirt", "a cozy knit sweater",
  "a leather biker jacket", "a traditional kimono", "an astronaut suit", "medieval knight armor", "a floral summer dress",
  "a hoodie and cargo pants", "a superhero costume", "a vintage 1920s outfit", "a chef uniform", "a cyberpunk jacket with neon trim"];
const ADDS = ["sunglasses", "a flower crown", "falling snow", "glowing fireflies", "a rainbow in the sky", "fireworks in the sky",
  "cherry blossom petals in the air", "a cute cat next to them", "neon signs in the background", "a hot air balloon in the sky",
  "a golden crown", "butterflies around", "a cozy scarf", "soft fog", "a full moon", "bubbles floating around"];
const SCENE_EDITS = ["make it a snowy winter night", "make it a foggy autumn morning", "make it golden hour sunset light",
  "turn day into night with city lights", "make it rainy and moody", "make it look underwater", "make it a sunny tropical beach day",
  "make it a frozen ice world", "make it a candle-lit evening", "make it spring with blooming flowers", "make everything made of gold",
  "make it a desert at noon", "make it look like a stormy evening with lightning"];
const MEDIUMS = ["an oil painting", "a watercolor painting", "a pencil sketch", "a comic book panel", "pixel art", "a stained glass window",
  "a Van Gogh painting", "a pop art poster", "a claymation scene", "an anime illustration", "a 3D cartoon", "a charcoal drawing",
  "a ukiyo-e woodblock print", "a LEGO scene", "a vintage 1970s photo", "a neon sign", "a marble statue", "a mosaic"];
const PLACES_BG = ["a Paris street", "a misty forest", "a neon Tokyo street", "a beach at sunset", "outer space", "a snowy mountain",
  "a cozy cafe", "a field of sunflowers", "a futuristic city", "an ancient temple", "a castle garden", "a desert at dusk"];
const REMIX_GRAMMAR = [
  () => `make the hair ${pick(COLORS)}`,
  () => `dress them in ${pick(OUTFITS)}`,
  () => `add ${pick(ADDS)}`,
  () => pick(SCENE_EDITS),
  () => `turn it into ${pick(MEDIUMS)}`,
  () => `replace the background with ${pick(PLACES_BG)}`,
  () => `make the hair ${pick(COLORS)} and add ${pick(ADDS)}`,
  () => `${pick(SCENE_EDITS)} and add ${pick(ADDS)}`,
];

// ---------- memory: never repeat ----------
const STORE = "luchii_surprise_seen_v2";
const load = () => { try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch { return {}; } };
const save = (m) => { try { localStorage.setItem(STORE, JSON.stringify(m)); } catch { /* private mode */ } };

function fresh(bucket, gen, keyOf = (x) => x.text, keyWindow = 25) {
  const mem = load();
  const seen = mem[bucket] || [];
  const recentKeys = (mem[`${bucket}:keys`] || []).slice(-keyWindow);
  let out = null;
  for (let i = 0; i < 400 && !out; i++) {
    const c = gen();
    if (!seen.includes(c.text) && !recentKeys.includes(keyOf(c))) out = c;
  }
  out = out || gen();
  mem[bucket] = [...seen, out.text].slice(-300);
  mem[`${bucket}:keys`] = [...recentKeys, keyOf(out)].slice(-keyWindow);
  save(mem);
  return out.text;
}

const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const join = (...parts) => parts.filter(Boolean).join(", ");

function textIdea(style) {
  const looks = LOOKS[style] || LOOKS.cinematic;
  if (style === "product") {
    const p = pick(PRODUCTS);
    const [l1, l2] = [...looks].sort(() => Math.random() - 0.5);
    return { key: p, text: cap(join(`${p} ${pick(PRODUCT_SETS)}`, pick(PALETTES), l1, maybe(0.5, l2))) };
  }
  const s = pick(SUBJECTS);
  const living = LIVING.test(s);
  const water = WATER.test(s);
  const indoor = !water && Math.random() < 0.25;
  const place = water ? pick(WATER_PLACES) : indoor ? pick(INDOOR) : pick(OUTDOOR);
  const when = indoor ? pick(LIGHTS) : pick(TIMES);
  const act = () => (living && Math.random() < 0.6 ? pick(LIVING_ACTIONS) : pick(FRAMING));
  const templates = [
    () => join(`${s} ${act()}`.trim() + ` ${place} ${when}`, `${pick(MOODS)} atmosphere`, pick(PALETTES), pick(looks)),
    () => join(`${pick(MOODS)} scene of ${s} ${place}`, when, pick(looks), maybe(0.6, pick(PALETTES))),
    () => join(`${s} ${place}`, when, act(), pick(PALETTES), pick(looks)),
    () => join(`${s} ${place}`, act(), `${pick(MOODS)} mood`, pick(looks)),
  ];
  return { key: s, text: cap(pick(templates)().replace(/\s+,/g, ",").replace(/,\s*,/g, ",").replace(/\s{2,}/g, " ")) };
}

// A new, never-before-seen prompt each click, shaped by the current style and mode.
export function surprisePrompt(mode = "text", style = "cinematic") {
  if (mode === "image") {
    return fresh("remix", () => { const t = pick(REMIX_GRAMMAR)(); return { key: t, text: t }; }, (x) => x.key);
  }
  return fresh(`text:${style}`, () => textIdea(style), (x) => x.key, style === "product" ? 8 : 25);
}

const OBJECTS_3D = ["treasure chest", "robot", "sports car", "potted cactus", "sword", "armchair", "teapot", "spaceship", "mushroom house",
  "dragon figurine", "lantern", "skateboard", "fox", "castle tower", "rocket", "guitar", "burger", "sneaker", "owl", "helmet",
  "hot air balloon", "cupcake", "anchor", "crown", "submarine", "tree stump", "penguin", "camera", "motorbike", "shield",
  "crystal", "mailbox", "dinosaur", "lighthouse", "backpack", "rubber duck"];
const MATERIALS_3D = ["wooden", "cartoon", "low poly", "golden", "glossy red", "stone", "chrome", "pastel", "clay", "steampunk brass",
  "glass", "neon", "candy", "mossy", "toy plastic", "marble", "rusty iron", "ice"];
const STYLE_3D = ["", "", "cute stylized", "game-ready", "chunky", "tiny", "detailed", "simple"];

export function surprise3D() {
  return fresh("3d", () => {
    const o = pick(OBJECTS_3D);
    const t = [pick(STYLE_3D), pick(MATERIALS_3D), o].filter(Boolean).join(" ");
    return { key: o, text: `${/^[aeiou]/i.test(t) ? "an" : "a"} ${t}` };
  }, (x) => x.key);
}

// Same never-repeat memory for any fixed idea list (video, 3D...): a shuffled deck that only
// reshuffles after every idea has been shown once.
export function freshFromList(bucket, list, current) {
  const mem = load();
  const key = `deck:${bucket}`;
  let deck = (mem[key] || []).filter((i) => i < list.length);
  if (!deck.length) deck = [...list.keys()].sort(() => Math.random() - 0.5);
  let idx = deck.shift();
  if (list[idx] === current && deck.length) { deck.push(idx); idx = deck.shift(); }
  mem[key] = deck;
  save(mem);
  return list[idx];
}

// Random subset of presets, excluding the ones just shown so the row keeps changing.
export function rotatePresets(pool, count, exclude = []) {
  const left = pool.filter((p) => !exclude.includes(p.id));
  const src = left.length >= count ? left : pool;
  return [...src].sort(() => Math.random() - 0.5).slice(0, count);
}
