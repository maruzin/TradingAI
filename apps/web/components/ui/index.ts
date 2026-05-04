/**
 * Barrel export for the design-system primitives.
 *
 * Import from `@/components/ui` (not the individual files) so the import
 * surface stays consistent and call sites can pick what they need without
 * worrying about file paths.
 */
export { Button } from "./button";
export { Card } from "./card";
export { Badge } from "./badge";
export { Input, Select, Textarea } from "./input";
export { Tabs } from "./tabs";
export { Tooltip } from "./tooltip";
export { EmptyState, ErrorState, LoadingState } from "./states";
