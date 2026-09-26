import { useId } from "react";

// Jeva: original illustrated support assistant.
export default function Jeva({ size = 40, label }) {
  const clip = useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className="jeva"
    >
      <defs>
        <clipPath id={clip}><circle cx="60" cy="60" r="60" /></clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <rect width="120" height="120" fill="#00A4A6" />
        <circle cx="60" cy="60" r="48" fill="#1FB8BA" opacity=".55" />
        <path d="M33 60 C31 30 47 21 61 21 C80 21 91 34 88 62 C88 78 85 88 81 94 L39 94 C35 86 33 74 33 60Z" fill="#4A2E2A" />
        <path d="M14 124 C18 96 40 86 60 86 C80 86 102 96 106 124Z" fill="#0A2540" />
        <path d="M49 86 L60 99 L71 86" fill="none" stroke="#EBF7F7" strokeWidth="3" strokeLinejoin="round" />
        <rect x="53" y="74" width="14" height="14" rx="4" fill="#E7B48F" />
        <ellipse cx="60" cy="57" rx="22" ry="25" fill="#F5CDB0" />
        <path d="M37 54 C37 35 50 28 63 29 C77 30 85 39 84 52 C76 43 62 39 51 45 C45 48 41 51 37 54Z" fill="#4A2E2A" />
        <ellipse className="eye" cx="51" cy="59" rx="2.8" ry="3.4" fill="#0A2540" />
        <ellipse className="eye" cx="69" cy="59" rx="2.8" ry="3.4" fill="#0A2540" />
        <circle cx="46" cy="67" r="3.6" fill="#F58220" opacity=".28" />
        <circle cx="74" cy="67" r="3.6" fill="#F58220" opacity=".28" />
        <path d="M52 68 Q60 76 68 68" fill="none" stroke="#0A2540" strokeWidth="2.6" strokeLinecap="round" />
        <path d="M34 58 C33 26 87 26 86 58" fill="none" stroke="#0A2540" strokeWidth="4" strokeLinecap="round" />
        <rect x="29" y="52" width="9" height="14" rx="4" fill="#F58220" />
        <rect x="82" y="52" width="9" height="14" rx="4" fill="#F58220" />
        <path d="M33 65 Q36 78 49 77" fill="none" stroke="#0A2540" strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="50" cy="77" r="2.6" fill="#F58220" />
      </g>
    </svg>
  );
}
