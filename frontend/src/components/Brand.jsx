import lockup from "@/assets/aptivon-lockup.png"
import mark from "@/assets/aptivon-mark.png"
import wordmark from "@/assets/aptivon-wordmark.png"

// The APTIVON logo. `lg` is the whole logo (with "by GLOBX") for the sign-in card; the default is the compact one
// for the headers after sign-in: the AV mark and the name.
export default function Brand({ lg = false, className = "", ...rest }) {
  if (lg) return <img src={lockup} alt="APTIVON by GLOBX - Enterprise Assessment Platform" draggable={false} className={"mx-auto h-auto w-80 max-w-full " + className} {...rest} />
  return (
    <div className={"flex items-center gap-2 " + className} {...rest}>
      <img src={mark} alt="" draggable={false} className="h-6 w-auto" />
      <img src={wordmark} alt="APTIVON" draggable={false} className="h-[18px] w-auto" />
    </div>
  )
}
