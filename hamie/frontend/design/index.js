/**
 * Aggregates the design-token CSS files into a single Lit `css` result.
 *
 * The .css files are the single source of truth (plain, readable,
 * lintable CSS — see the header comment in each file for the HA-variable
 * verification behind every token). They are imported here as raw text
 * (via esbuild's `--loader:.css=text`, configured in package.json's
 * build:frontend script) and wrapped with `unsafeCSS` only because Lit's
 * `css` tagged template cannot itself interpolate external file content —
 * `unsafeCSS` is safe here since the input is our own build-time source
 * file, never user- or network-supplied content.
 *
 * Applied once, as `static styles` on the root <hamie-app> element (see
 * hamie-app.js) — CSS custom properties defined on a shadow root's host
 * are inherited by every descendant shadow tree, so nested components
 * never need to re-import these files themselves.
 */
import { css, unsafeCSS } from "lit";

import tokensCss from "./tokens.css";
import typographyCss from "./typography.css";
import spacingCss from "./spacing.css";
import motionCss from "./motion.css";
import elevationCss from "./elevation.css";

export const designTokens = css`
  ${unsafeCSS(tokensCss)}
  ${unsafeCSS(typographyCss)}
  ${unsafeCSS(spacingCss)}
  ${unsafeCSS(motionCss)}
  ${unsafeCSS(elevationCss)}
`;
