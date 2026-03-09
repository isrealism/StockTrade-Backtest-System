import { useState, useCallback } from "react";
import { Input } from "@/components/ui/input";

/**
 * 解决受控 number input 无法输入小数/中间态的问题。
 *
 * onChange 时只保存原始字符串草稿（draft），
 * onBlur 失焦时才将草稿转为数字并调用 onChange 回调写回外部 state。
 */
export function useNumberInput(
  value: number,
  onChange: (num: number) => void,
  options?: {
    display?: (v: number) => string;
    parse?: (s: string) => number;
    clamp?: (n: number) => number;
  }
) {
  const display = options?.display ?? String;
  const parse = options?.parse ?? parseFloat;
  const clamp = options?.clamp ?? ((n: number) => n);

  const [draft, setDraft] = useState<string | null>(null);

  const inputValue = draft !== null ? draft : display(value);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setDraft(e.target.value);
    },
    []
  );

  const handleBlur = useCallback(() => {
    if (draft !== null) {
      const num = parse(draft);
      if (!isNaN(num)) {
        onChange(clamp(num));
      }
      setDraft(null);
    }
  }, [draft, parse, clamp, onChange]);

  return { inputValue, handleChange, handleBlur } as const;
}

// ─────────────────────────────────────────────────────────────────────────────
// NumericInput — 封装了 useNumberInput 的独立组件
// 用于循环动态渲染的参数列表（Hook 不能在循环内调用）
// ─────────────────────────────────────────────────────────────────────────────

interface NumericInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  value: number;
  onChange: (num: number) => void;
  display?: (v: number) => string;
  parse?: (s: string) => number;
  clamp?: (n: number) => number;
  className?: string;
}

export function NumericInput({
  value,
  onChange,
  display,
  parse,
  clamp,
  className,
  ...rest
}: NumericInputProps) {
  const inp = useNumberInput(value, onChange, { display, parse, clamp });
  return (
    <Input
      type="number"
      value={inp.inputValue}
      onChange={inp.handleChange}
      onBlur={inp.handleBlur}
      className={className}
      {...rest}
    />
  );
}