import lockup from "@/assets/kautilya-lockup.png"
import mark from "@/assets/kautilya-mark.png"
import wordmark from "@/assets/kautilya-wordmark.png"

// The KAUTILYA logo. `lg` is the whole logo (with "by GLOBX") for the sign-in card; the default is the compact one
// (the K mark and the name on one line, no "by GLOBX") for every screen after sign-in. Widths are set and heights follow
// (h-auto), so a picture can never be stretched or squeezed.
export default function Brand({ lg = false, className = "", ...rest }) {
  if (lg) return <img src={lockup} alt="KAUTILYA by GLOBX - Assessment Platform" draggable={false} className={"mx-auto h-auto w-80 max-w-full " + className} {...rest} />
  return (
    <div className={"flex items-center gap-2 " + className} {...rest}>
      <img src={mark} alt="" draggable={false} className="h-auto w-8" />
      <img src={wordmark} alt="KAUTILYA" draggable={false} className="h-auto w-32" />
    </div>
  )
}
