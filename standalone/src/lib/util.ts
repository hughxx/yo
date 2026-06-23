// 简单唯一 id（用于规则 / 群组等列表项 key）。
export function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

// 逗号（中英文）分隔成去空白的字符串数组。
export function splitList(v: string): string[] {
  return v
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
}
