!     MATMUL and TRANSPOSE for the FORTRAN 77 lane.
!
!     f2c implements F77, which has no array-valued intrinsics. tools/f77ify.py rewrites
!     matmul()/transpose() into calls on these, the same way it rewrites maxval()/sum()
!     into bridge/ccx_reductions.f -- a temporary per intermediate result, sized from the
!     declarations, with the loops living here rather than being generated inline.
!
!     Every routine takes the DECLARED leading dimension of each operand separately from
!     its logical extent. That is not ceremony: patch.f's HYBSVD call is in this repository
!     precisely because a bounded array whose leading dimension is passed as the runtime
!     count indexes wrong, silently. Callers pass the declared bound.
!
!     The output is always a distinct array from the inputs, so `a = matmul(b,a)` is safe:
!     f77ify assigns into a temporary and copies afterwards.

!     c(m,n) = a(m,k) * b(k,n)
      subroutine fcwmm(a,lda,b,ldb,c,ldc,m,k,n)
      implicit none
      integer lda,ldb,ldc,m,k,n,i,j,l
      real*8 a(lda,*),b(ldb,*),c(ldc,*),s
      do j=1,n
         do i=1,m
            s=0.d0
            do l=1,k
               s=s+a(i,l)*b(l,j)
            enddo
            c(i,j)=s
         enddo
      enddo
      return
      end

!     c(m) = a(m,k) * b(k)        -- matrix times vector
      subroutine fcwmv(a,lda,b,c,m,k)
      implicit none
      integer lda,m,k,i,l
      real*8 a(lda,*),b(*),c(*),s
      do i=1,m
         s=0.d0
         do l=1,k
            s=s+a(i,l)*b(l)
         enddo
         c(i)=s
      enddo
      return
      end

!     c(n) = a(k) * b(k,n)        -- vector times matrix
      subroutine fcwvm(a,b,ldb,c,k,n)
      implicit none
      integer ldb,k,n,j,l
      real*8 a(*),b(ldb,*),c(*),s
      do j=1,n
         s=0.d0
         do l=1,k
            s=s+a(l)*b(l,j)
         enddo
         c(j)=s
      enddo
      return
      end

!     at(n,m) = transpose(a(m,n))
      subroutine fcwtr(a,lda,at,ldat,m,n)
      implicit none
      integer lda,ldat,m,n,i,j
      real*8 a(lda,*),at(ldat,*)
      do j=1,n
         do i=1,m
            at(j,i)=a(i,j)
         enddo
      enddo
      return
      end
