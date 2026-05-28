import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'src-tauri', 'target', '**/target/**', 'crates/**/target/**']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactRefresh.configs.vite,
    ],
    plugins: {
      'react-hooks': reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // Core hooks rules only — skip React Compiler checks (v7 bundles them)
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Pre-existing across codebase — fix incrementally
      '@typescript-eslint/no-explicit-any': 'warn',
      'react-refresh/only-export-components': 'warn',
      // Allow intentionally-unused args/vars with underscore prefix
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          destructuredArrayIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // AVSDLC visual-evidence contract
      // (docs/methodology/avsdlc-visual-evidence-contract.md §rows for color
      // token usage and minimum stream text). Surfaces the two visual-governance
      // dimensions in `pnpm lint` (the web-build CI job). Severity is 'warn' for
      // now: the codebase still carries pre-existing violations (e.g. sub-12px
      // fontSize in src/pages/FlowPage.tsx). Escalate to 'error' — the contract's
      // CI-fail condition — once those are migrated to zero.
      'no-restricted-syntax': [
        'warn',
        {
          // §3 color contract: no hardcoded hex in components. Exemptions (§8.2):
          // detection overlays, IR presets, compositor void #0a0a0a — plus the
          // palette token definition, exempted by the override block below.
          selector:
            "Literal[value=/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/]",
          message:
            'Hardcoded hex color: derive from a semantic palette token (CSS var / Tailwind) per docs/logos-design-language.md §3. Exemptions (§8.2): detection overlays, IR presets, compositor void #0a0a0a — disable inline with justification.',
        },
        {
          // §12.1 minimum stream text: >= 12px for stream-visible text. Catches
          // numeric fontSize literals; px-string values and <RedactWhenLive>
          // context are a follow-up refinement.
          selector: "Property[key.name='fontSize'] > Literal[value<12]",
          message:
            'On-stream text minimum is 12px (docs/logos-design-language.md §12.1). Raise to >=12px, or wrap the surface in <RedactWhenLive>.',
        },
      ],
    },
  },
  {
    // The palette token table legitimately defines hex values; the color
    // contract governs *component* usage, not the token source of truth.
    files: ['src/theme/palettes.ts'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
])
