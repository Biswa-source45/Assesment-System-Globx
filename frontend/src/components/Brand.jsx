import lockup from "@/assets/aptivon-lockup.png"
import mark from "@/assets/aptivon-mark.png"
import wordmark from "@/assets/aptivon-wordmark.png"
import byGlobx from "@/assets/by-globx.png"

// The APTIVON logo. `lg` is the whole logo for the sign-in card; the default is the compact one for a 48px header:
// the AV mark, the name, and "by GLOBX" under the name.
export default function Brand({ lg = false, className = "", ...rest }) {
  if (lg) return <img src={lockup} alt="APTIVON by GLOBX - Enterprise Assessment Platform" draggable={false} className={"mx-auto h-auto w-80 max-w-full " + className} {...rest} />
  return (
    <div className={"flex items-center gap-2.5 " + className} {...rest}>
      <img src={mark} alt="" draggable={false} className="h-7 w-auto" />
      <div className="flex flex-col gap-[5px]">
        <img src={wordmark} alt="APTIVON" draggable={false} className="h-[18px] w-auto" />
        <img src={byGlobx} alt="by GLOBX" draggable={false} className="ml-0.5 h-[9px] w-auto" />
      </div>
    </div>
  )
}
