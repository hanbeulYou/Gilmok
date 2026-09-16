import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules/**", ".venv/**", ".local/**", "supabase/.temp/**"] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
);
