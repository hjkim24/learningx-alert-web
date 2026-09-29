// LearningX Alert design system -> Figma.
// Source of truth: DESIGN.md at the repo root. Keep TOKENS in sync with it.
// Run as a development plugin (Plugins -> Development -> Import plugin from
// manifest). Re-running updates the variables/styles in place and rebuilds
// the "LearningX Design System" page. It never touches other pages.

const TOKENS = {
  color: {
    ink: "#1B2233",
    muted: "#5F6778",
    brand: "#2C4380",
    "brand-strong": "#223566",
    "brand-soft": "#E5EAF5",
    mist: "#EEF1F6",
    surface: "#FFFFFF",
    "surface-2": "#F5F7FA",
    line: "#DADFE8",
    urgent: "#E2A93B",
    "urgent-soft": "#FBF1DA",
    lake: "#276C66",
    "lake-soft": "#E3F1EF",
    clay: "#B8483A",
    "clay-soft": "#F8E6E2",
  },
  colorGroups: {
    brand: ["brand", "brand-strong", "brand-soft"],
    neutral: ["ink", "muted", "mist", "surface", "surface-2", "line"],
    status: ["urgent", "urgent-soft", "lake", "lake-soft", "clay", "clay-soft"],
  },
  space: [4, 8, 12, 16, 24, 32, 48, 64],
  radius: { sheet: 24, block: 16, control: 12, pill: 999 },
  // 1.25 scale: 12.8 / 14 / 16 / 20 / 25 / 31px
  type: [
    { name: "Page title", size: 31, weight: "Bold", lineHeight: 130, letterSpacing: -2 },
    { name: "Section title", size: 20, weight: "Bold", lineHeight: 130, letterSpacing: -2 },
    { name: "Subsection", size: 17, weight: "Bold", lineHeight: 130, letterSpacing: -2 },
    { name: "Body", size: 16, weight: "Regular", lineHeight: 160, letterSpacing: 0 },
    { name: "Small", size: 14, weight: "Regular", lineHeight: 160, letterSpacing: 0 },
    { name: "Meta", size: 12.8, weight: "Regular", lineHeight: 160, letterSpacing: 0 },
  ],
  shadow: {
    sheet: [
      { y: 1, blur: 2, spread: 0, alpha: 0.05 },
      { y: 12, blur: 32, spread: -16, alpha: 0.18 },
    ],
    float: [{ y: 8, blur: 24, spread: -8, alpha: 0.22 }],
  },
  shadowRgb: { r: 27 / 255, g: 34 / 255, b: 51 / 255 },
};

const PAGE_NAME = "LearningX Design System";
const COLLECTION = "LearningX Alert";
const FONT_FAMILIES = ["Pretendard", "Apple SD Gothic Neo", "Noto Sans KR", "Inter"];

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}

async function pickFont() {
  const available = await figma.listAvailableFontsAsync();
  for (const family of FONT_FAMILIES) {
    const styles = available.filter((f) => f.fontName.family === family).map((f) => f.fontName.style);
    const regular = styles.find((s) => s === "Regular") || styles[0];
    const bold = styles.find((s) => s === "Bold") || styles.find((s) => /bold/i.test(s)) || regular;
    if (regular) {
      const fonts = { Regular: { family, style: regular }, Bold: { family, style: bold } };
      await figma.loadFontAsync(fonts.Regular);
      await figma.loadFontAsync(fonts.Bold);
      return fonts;
    }
  }
  throw new Error("No usable font found");
}

// ---------- Variables ----------

async function upsertVariables() {
  const collections = await figma.variables.getLocalVariableCollectionsAsync();
  let collection = collections.find((c) => c.name === COLLECTION);
  if (!collection) collection = figma.variables.createVariableCollection(COLLECTION);
  const mode = collection.modes[0].modeId;
  collection.renameMode(mode, "Default");

  const existing = {};
  for (const id of collection.variableIds) {
    const v = await figma.variables.getVariableByIdAsync(id);
    if (v) existing[v.name] = v;
  }
  function upsert(name, type, value, scopes) {
    let v = existing[name];
    if (!v || v.resolvedType !== type) v = figma.variables.createVariable(name, collection, type);
    v.setValueForMode(mode, value);
    if (scopes) v.scopes = scopes;
    return v;
  }

  const colors = {};
  for (const [group, names] of Object.entries(TOKENS.colorGroups)) {
    for (const name of names) {
      colors[name] = upsert(`color/${group}/${name}`, "COLOR", hexToRgb(TOKENS.color[name]));
    }
  }
  TOKENS.space.forEach((px) => upsert(`space/${px}`, "FLOAT", px, ["GAP", "WIDTH_HEIGHT"]));
  for (const [name, px] of Object.entries(TOKENS.radius)) {
    upsert(`radius/${name}`, "FLOAT", px, ["CORNER_RADIUS"]);
  }
  return colors;
}

function bound(colorVar) {
  const paint = { type: "SOLID", color: { r: 0, g: 0, b: 0 } };
  return figma.variables.setBoundVariableForPaint(paint, "color", colorVar);
}

// ---------- Styles ----------

async function upsertStyles(colors, fonts) {
  const paintStyles = await figma.getLocalPaintStylesAsync();
  for (const [name, variable] of Object.entries(colors)) {
    const styleName = `LearningX/${name}`;
    const style = paintStyles.find((s) => s.name === styleName) || figma.createPaintStyle();
    style.name = styleName;
    style.paints = [bound(variable)];
  }

  const textStyles = await figma.getLocalTextStylesAsync();
  const created = {};
  for (const t of TOKENS.type) {
    const styleName = `LearningX/${t.name}`;
    const style = textStyles.find((s) => s.name === styleName) || figma.createTextStyle();
    style.name = styleName;
    style.fontName = fonts[t.weight];
    style.fontSize = t.size;
    style.lineHeight = { unit: "PERCENT", value: t.lineHeight };
    style.letterSpacing = { unit: "PERCENT", value: t.letterSpacing };
    created[t.name] = style;
  }

  const effectStyles = await figma.getLocalEffectStylesAsync();
  const effects = {};
  for (const [name, layers] of Object.entries(TOKENS.shadow)) {
    const styleName = `LearningX/shadow-${name}`;
    const style = effectStyles.find((s) => s.name === styleName) || figma.createEffectStyle();
    style.name = styleName;
    style.effects = layers.map((l) => ({
      type: "DROP_SHADOW",
      color: Object.assign({}, TOKENS.shadowRgb, { a: l.alpha }),
      offset: { x: 0, y: l.y },
      radius: l.blur,
      spread: l.spread,
      visible: true,
      blendMode: "NORMAL",
    }));
    effects[name] = style;
  }
  return { text: created, effects };
}

// ---------- Helpers for the page ----------

function autoFrame(name, dir, gap, pad) {
  const f = figma.createFrame();
  f.name = name;
  f.layoutMode = dir;
  f.itemSpacing = gap;
  f.paddingTop = f.paddingBottom = f.paddingLeft = f.paddingRight = pad || 0;
  f.primaryAxisSizingMode = "AUTO";
  f.counterAxisSizingMode = "AUTO";
  f.fills = [];
  return f;
}

async function text(content, style, colorVar) {
  const node = figma.createText();
  await node.setTextStyleIdAsync(style.id);
  node.characters = content;
  node.fills = [bound(colorVar)];
  return node;
}

// ---------- Components (DESIGN.md "컴포넌트 규칙") ----------

async function buildComponents(c, styles) {
  const t = styles.text;
  const out = [];

  async function button(label, fill, color) {
    const comp = figma.createComponent();
    comp.layoutMode = "HORIZONTAL";
    comp.primaryAxisAlignItems = "CENTER";
    comp.counterAxisAlignItems = "CENTER";
    comp.paddingLeft = comp.paddingRight = 20;
    comp.resize(120, 44);
    comp.primaryAxisSizingMode = "AUTO";
    comp.counterAxisSizingMode = "FIXED";
    comp.cornerRadius = TOKENS.radius.control;
    comp.fills = fill ? [bound(fill)] : [];
    comp.appendChild(await text(label, t["Small"], color));
    comp.children[0].fontName = styles.fonts.Bold;
    return comp;
  }
  const primary = await button("설정 저장", c.brand, c.surface);
  primary.name = "Button/Primary";
  const secondary = await button("다시 조회", c["surface-2"], c.ink);
  secondary.name = "Button/Secondary";
  const danger = await button("삭제", null, c.clay);
  danger.name = "Button/Danger";
  out.push(primary, secondary, danger);

  async function badge(name, label, fill, color, tag) {
    const comp = figma.createComponent();
    comp.name = name;
    comp.layoutMode = "HORIZONTAL";
    comp.paddingLeft = comp.paddingRight = 10;
    comp.paddingTop = comp.paddingBottom = 2;
    comp.primaryAxisSizingMode = "AUTO";
    comp.counterAxisSizingMode = "AUTO";
    if (tag) {
      comp.topLeftRadius = comp.topRightRadius = comp.bottomRightRadius = 999;
      comp.bottomLeftRadius = 4;
    } else {
      comp.cornerRadius = TOKENS.radius.pill;
    }
    comp.fills = [bound(fill)];
    const label_ = await text(label, t["Meta"], color);
    label_.fontName = styles.fonts.Bold;
    comp.appendChild(label_);
    return comp;
  }
  out.push(
    await badge("Badge/D-day", "D-2", c.urgent, c.ink, true),
    await badge("Badge/Assignment", "과제", c["brand-soft"], c.brand, false),
    await badge("Badge/Lecture", "강의", c["lake-soft"], c.lake, false),
    await badge("Badge/Failed", "실패", c["clay-soft"], c.clay, false)
  );

  async function toggle(name, label, on) {
    const comp = figma.createComponent();
    comp.name = name;
    comp.layoutMode = "HORIZONTAL";
    comp.paddingLeft = comp.paddingRight = 14;
    comp.paddingTop = comp.paddingBottom = 8;
    comp.primaryAxisSizingMode = "AUTO";
    comp.counterAxisSizingMode = "AUTO";
    comp.cornerRadius = TOKENS.radius.control;
    comp.fills = [bound(on ? c["brand-soft"] : c["surface-2"])];
    const l = await text(label, t["Small"], on ? c.brand : c.muted);
    l.fontName = styles.fonts.Bold;
    comp.appendChild(l);
    return comp;
  }
  out.push(await toggle("Toggle/On", "과제", true), await toggle("Toggle/Off", "강의", false));

  async function callout(name, body, fill) {
    const comp = figma.createComponent();
    comp.name = name;
    comp.layoutMode = "VERTICAL";
    comp.paddingLeft = comp.paddingRight = 20;
    comp.paddingTop = comp.paddingBottom = 16;
    comp.resize(360, 10);
    comp.primaryAxisSizingMode = "AUTO";
    comp.counterAxisSizingMode = "FIXED";
    comp.cornerRadius = TOKENS.radius.block;
    comp.fills = [bound(fill)];
    const b = await text(body, t["Small"], c.ink);
    comp.appendChild(b);
    b.layoutSizingHorizontal = "FILL";
    return comp;
  }
  out.push(
    await callout("Callout/Warning", "켜 둔 알림 시각이 없어 예약 알림이 가지 않아요.", c["urgent-soft"]),
    await callout("Callout/Error", "Canvas에 연결하지 못했어요. 토큰을 다시 확인해 주세요.", c["clay-soft"])
  );

  const toast = figma.createComponent();
  toast.name = "Toast/Success";
  toast.layoutMode = "HORIZONTAL";
  toast.itemSpacing = 12;
  toast.paddingLeft = toast.paddingRight = 16;
  toast.paddingTop = toast.paddingBottom = 12;
  toast.primaryAxisSizingMode = "AUTO";
  toast.counterAxisSizingMode = "AUTO";
  toast.cornerRadius = TOKENS.radius.block;
  toast.fills = [bound(c.surface)];
  await toast.setEffectStyleIdAsync(styles.effects.float.id);
  toast.appendChild(await text("설정을 저장했어요.", t["Small"], c.ink));
  out.push(toast);

  const input = figma.createComponent();
  input.name = "Input";
  input.layoutMode = "HORIZONTAL";
  input.counterAxisAlignItems = "CENTER";
  input.paddingLeft = input.paddingRight = 14;
  input.resize(280, 44);
  input.primaryAxisSizingMode = "FIXED";
  input.counterAxisSizingMode = "FIXED";
  input.cornerRadius = TOKENS.radius.control;
  input.fills = [bound(c["surface-2"])];
  input.appendChild(await text("Canvas 토큰", t["Body"], c.muted));
  out.push(input);

  return out;
}

// ---------- Page ----------

async function buildPage(colors, styles) {
  await figma.loadAllPagesAsync();
  const old = figma.root.children.find((p) => p.name === PAGE_NAME);
  const page = figma.createPage();
  page.name = PAGE_NAME;
  await figma.setCurrentPageAsync(page);
  if (old) old.remove();

  const t = styles.text;
  const root = autoFrame("Design System", "VERTICAL", 48, 64);
  root.fills = [bound(colors.mist)];
  page.appendChild(root);

  root.appendChild(await text("LearningX Alert 디자인 시스템", t["Page title"], colors.ink));
  root.appendChild(
    await text("DESIGN.md 기준. 남색 브랜드는 조용히, 호박색은 마감이 임박했을 때만.", t["Body"], colors.muted)
  );

  // Colors
  const colorSection = autoFrame("Colors", "VERTICAL", 16);
  colorSection.appendChild(await text("색", t["Section title"], colors.ink));
  for (const [group, names] of Object.entries(TOKENS.colorGroups)) {
    const row = autoFrame(group, "HORIZONTAL", 16);
    for (const name of names) {
      const cell = autoFrame(name, "VERTICAL", 8);
      const sw = figma.createRectangle();
      sw.resize(120, 72);
      sw.cornerRadius = TOKENS.radius.block;
      sw.fills = [bound(colors[name])];
      sw.strokes = [bound(colors.line)];
      sw.strokeWeight = 1;
      cell.appendChild(sw);
      cell.appendChild(await text(`--${name}`, t["Meta"], colors.ink));
      cell.appendChild(await text(TOKENS.color[name], t["Meta"], colors.muted));
      row.appendChild(cell);
    }
    colorSection.appendChild(row);
  }
  root.appendChild(colorSection);

  // Type
  const typeSection = autoFrame("Typography", "VERTICAL", 12);
  typeSection.appendChild(await text("타이포그래피", t["Section title"], colors.ink));
  for (const spec of TOKENS.type) {
    typeSection.appendChild(await text(`${spec.name} · ${spec.size}px — 과제 마감까지 D-2`, t[spec.name], colors.ink));
  }
  root.appendChild(typeSection);

  // Spacing + radius
  const spaceSection = autoFrame("Spacing & Radius", "VERTICAL", 16);
  spaceSection.appendChild(await text("간격과 모서리", t["Section title"], colors.ink));
  const spaceRow = autoFrame("space", "HORIZONTAL", 16);
  spaceRow.counterAxisAlignItems = "MAX";
  for (const px of TOKENS.space) {
    const cell = autoFrame(`space-${px}`, "VERTICAL", 8);
    const bar = figma.createRectangle();
    bar.resize(px, px);
    bar.fills = [bound(colors.brand)];
    cell.appendChild(bar);
    cell.appendChild(await text(`${px}`, t["Meta"], colors.muted));
    spaceRow.appendChild(cell);
  }
  spaceSection.appendChild(spaceRow);
  const radiusRow = autoFrame("radius", "HORIZONTAL", 16);
  for (const [name, px] of Object.entries(TOKENS.radius)) {
    const cell = autoFrame(`radius-${name}`, "VERTICAL", 8);
    const box = figma.createRectangle();
    box.resize(96, 64);
    box.cornerRadius = Math.min(px, 32);
    box.fills = [bound(colors.surface)];
    box.strokes = [bound(colors.line)];
    cell.appendChild(box);
    cell.appendChild(await text(`${name} ${px}px`, t["Meta"], colors.muted));
    radiusRow.appendChild(cell);
  }
  spaceSection.appendChild(radiusRow);
  root.appendChild(spaceSection);

  // Components
  const compSection = autoFrame("Components", "VERTICAL", 16);
  compSection.appendChild(await text("컴포넌트", t["Section title"], colors.ink));
  const sheet = autoFrame("Sheet", "HORIZONTAL", 24, 32);
  sheet.layoutWrap = "WRAP";
  sheet.counterAxisSpacing = 24;
  sheet.resize(960, 10);
  sheet.primaryAxisSizingMode = "FIXED";
  sheet.cornerRadius = TOKENS.radius.sheet;
  sheet.fills = [bound(colors.surface)];
  await sheet.setEffectStyleIdAsync(styles.effects.sheet.id);
  for (const comp of await buildComponents(colors, styles)) sheet.appendChild(comp);
  compSection.appendChild(sheet);
  root.appendChild(compSection);

  figma.viewport.scrollAndZoomIntoView([root]);
}

(async () => {
  try {
    const fonts = await pickFont();
    const colors = await upsertVariables();
    const styles = await upsertStyles(colors, fonts);
    styles.fonts = fonts;
    await buildPage(colors, styles);
    figma.closePlugin(`LearningX 디자인 시스템을 만들었어요 (글꼴: ${fonts.Regular.family}).`);
  } catch (error) {
    figma.closePlugin(`실패: ${error && error.message ? error.message : error}`);
  }
})();
