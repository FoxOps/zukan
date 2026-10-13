import { Link } from 'react-router'

export default function NotFound() {
  return (
    <div className="hero min-h-[50vh]">
      <div className="hero-content text-center">
        <div>
          <h1 className="text-4xl font-bold">Not found</h1>
          <Link to="/" className="btn btn-primary mt-6">Back to dashboard</Link>
        </div>
      </div>
    </div>
  )
}
