import { Component } from "react"
import { Button } from "@/components/ui/button"

// A render error in one question must never leave a blank white page. Answers are saved on the server, so reloading is safe.
export default class ErrorBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error, info) {
    console.error("Screen crashed:", error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
        <div className="grid max-w-md gap-3 rounded-lg border bg-white p-6 text-center">
          <h1 className="text-xl font-semibold">Something went wrong on this screen</h1>
          <p className="text-sm text-muted-foreground">Your answers are saved. Reload the page to continue. If it happens again, tell the invigilator.</p>
          <div><Button onClick={() => window.location.reload()}>Reload</Button></div>
        </div>
      </div>
    )
  }
}
