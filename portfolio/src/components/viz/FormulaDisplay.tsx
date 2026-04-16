import { InlineMath, BlockMath } from "react-katex";

interface Props {
  latex: string;
  inline?: boolean;
  caption?: string;
}

export function FormulaDisplay({ latex, inline = false, caption }: Props) {
  const Math = inline ? InlineMath : BlockMath;
  return (
    <figure className="my-4">
      <div className="text-[var(--text-primary)] overflow-x-auto">
        <Math math={latex} />
      </div>
      {caption && (
        <figcaption className="text-xs font-mono text-[var(--text-tertiary)] mt-2 text-center">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}
