export default {
  extends: ['@commitlint/config-conventional'],
  rules: { 'body-max-line-length': [0], 'footer-max-line-length': [0] },
  // 055c3d9 was pushed with a 102-char header; history is never force-pushed, so exempt that one commit.
  ignores: [
    (m) => m.startsWith('fix(ci): first-party import classification independent of local checkouts;'),
    // aee570f: merge commit pushed with a non-standard "merge:" header (default "Merge ..." headers are ignored already)
    (m) => m.startsWith('merge: origin/main (SQL style, #17) into feat/any-repo'),
  ],
}
