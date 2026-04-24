export function Lang({
  zh,
  en,
}: {
  zh: React.ReactNode;
  en: React.ReactNode;
}) {
  return (
    <>
      <span className="lang-zh">{zh}</span>
      <span className="lang-en">{en}</span>
    </>
  );
}
