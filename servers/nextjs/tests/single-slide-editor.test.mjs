import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const presentationPageUrl = new URL(
  "../app/(presentation-generator)/presentation/components/PresentationPage.tsx",
  import.meta.url,
);
const slideContentUrl = new URL(
  "../app/(presentation-generator)/presentation/components/SlideContent.tsx",
  import.meta.url,
);
const presentationActionsUrl = new URL(
  "../app/(presentation-generator)/presentation/components/PresentationActions.tsx",
  import.meta.url,
);
const sidePanelUrl = new URL(
  "../app/(presentation-generator)/presentation/components/SidePanel.tsx",
  import.meta.url,
);
const slideThumbnailCardUrl = new URL(
  "../app/(presentation-generator)/presentation/components/SlideThumbnailCard.tsx",
  import.meta.url,
);
const presentationRenderUrl = new URL(
  "../app/(presentation-generator)/components/PresentationRender.tsx",
  import.meta.url,
);

test("editor renders only the selected slide without a scrolling deck", async () => {
  const [presentationPageSource, slideContentSource] = await Promise.all([
    readFile(presentationPageUrl, "utf8"),
    readFile(slideContentUrl, "utf8"),
  ]);

  assert.doesNotMatch(presentationPageSource, /SnapSlideDeck/);
  assert.doesNotMatch(
    presentationPageSource,
    /presentationData\.slides\.map\([\s\S]*?<SlideContent/,
  );
  assert.match(
    presentationPageSource,
    /activeEditorSlide[\s\S]*?<SlideContent[\s\S]*?fitToContainer/,
  );
  assert.match(
    presentationPageSource,
    /<div className="mx-auto h-full min-h-0 w-full">\s*<SlideContent/,
  );
  assert.match(slideContentSource, /<SlideActionBar/);
  assert.doesNotMatch(slideContentSource, /revealOnGroupHover/);
});

test("right tools rail stays visible and opens its panel on tab selection", async () => {
  const [presentationPageSource, presentationActionsSource] = await Promise.all([
    readFile(presentationPageUrl, "utf8"),
    readFile(presentationActionsUrl, "utf8"),
  ]);

  assert.match(presentationPageSource, /isRightPanelOpen \? "xl:w-\[383px\]" : "xl:w-\[78px\]"/);
  assert.match(presentationActionsSource, /onPanelOpenChange\(true\)/);
  assert.match(presentationActionsSource, /aria-label="Editor tools"/);
  assert.match(presentationActionsSource, /w-\[78px\][\s\S]*?px-\[10px\] py-2/);
  assert.match(
    presentationActionsSource,
    /\{panelOpen \? \([\s\S]*?<ActionsPanel[\s\S]*?<ActionsSidebar/,
  );
  assert.match(
    presentationActionsSource,
    /panelOpen && nextAction === activeAction[\s\S]*?onPanelOpenChange\(false\)/,
  );
  assert.match(presentationActionsSource, /actionIconSrc: Record<ActionId, string>/);
  assert.match(presentationPageSource, /aria-label="Close tools panel"/);
  assert.match(
    presentationPageSource,
    /h-\[36px\] w-\[16px\][\s\S]*?<ChevronRight/,
  );
  assert.match(presentationPageSource, /onClick=\{\(\) => setIsRightPanelOpen\(false\)\}/);
});

test("active slide thumbnail is obvious and remains in view", async () => {
  const [sidePanelSource, slideThumbnailCardSource] = await Promise.all([
    readFile(sidePanelUrl, "utf8"),
    readFile(slideThumbnailCardUrl, "utf8"),
  ]);

  assert.match(sidePanelSource, /data-slide-thumbnail-index/);
  assert.match(sidePanelSource, /scrollIntoView\(\{[\s\S]*?block: "nearest"/);
  assert.match(slideThumbnailCardSource, /aria-current=\{selected \? "true" : undefined\}/);
  assert.match(slideThumbnailCardSource, /border-2 border-\[#7A5AF8\]/);
  assert.match(slideThumbnailCardSource, /shadow-\[0_0_0_3px_rgba\(122,90,248,0\.16\)\]/);
});

test("active slide can scale above its authored size to fill the viewport", async () => {
  const presentationRenderSource = await readFile(presentationRenderUrl, "utf8");

  assert.match(
    presentationRenderSource,
    /if \(fitToContainer\)[\s\S]*?return Math\.min\(sx, sy\);/,
  );
  assert.doesNotMatch(
    presentationRenderSource,
    /if \(fitToContainer\)[\s\S]*?return Math\.min\(sx, sy, 1\);/,
  );
});

test("desktop editor centers and dismisses its navigation introduction", async () => {
  const presentationPageSource = await readFile(presentationPageUrl, "utf8");

  assert.match(presentationPageSource, /presenton:editor-navigation-hint:v1/);
  assert.match(presentationPageSource, /Navigate with/);
  assert.match(presentationPageSource, /or the left thumbnails/);
  assert.match(presentationPageSource, /Dismiss navigation hint/);
  assert.match(
    presentationPageSource,
    /style=\{\{ left: "50%", transform: "translateX\(-50%\)" \}\}/,
  );
  assert.match(
    presentationPageSource,
    /window\.setTimeout\(dismissNavigationHint, 5_000\)/,
  );
  assert.match(
    presentationPageSource,
    /navigationHintSlideRef\.current === selectedSlide[\s\S]*?return;[\s\S]*?dismissNavigationHint\(\)/,
  );
  assert.match(presentationPageSource, /NAVIGATION_SCROLL_THRESHOLD = 240/);
  assert.match(presentationPageSource, /NAVIGATION_SCROLL_WINDOW_MS = 800/);
  assert.match(
    presentationPageSource,
    /addEventListener\("wheel", handleWheel, \{ passive: true \}\)/,
  );
  assert.match(
    presentationPageSource,
    /scrollIntent\.amount < NAVIGATION_SCROLL_THRESHOLD[\s\S]*?setShowNavigationHint\(true\)/,
  );
});
